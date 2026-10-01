"""Regression tests for the release bump label contract."""

from __future__ import annotations

import json
import re
import subprocess  # noqa: S404
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
CONFIG_PATH = ROOT / ".github" / "version-drafter.yml"
LABELS_PATH = ROOT / ".github" / "labels.yml"
CHECKER_PATH = ROOT / "scripts" / "check_release_labels.py"
WORKFLOWS_PATH = ROOT / ".github" / "workflows"
DEPENDABOT_PATH = ROOT / ".github" / "dependabot.yml"

CANONICAL_CONFIG = """---
# Only explicit release-intent labels drive semantic version bumps.
major-labels:
  - "changes/major"
minor-labels:
  - "changes/minor"
patch-labels:
  - "changes/patch"
"""


def run_checker(
    labels: list[str],
    *,
    title: str = "fix: example",
    head_ref: str = "feature/example",
    author_login: str = "contributor",
    head_repository: str = "contributor/example",
) -> subprocess.CompletedProcess[str]:
    """Run the label checker as the workflow does."""
    return subprocess.run(  # noqa: S603
        [
            sys.executable,
            str(CHECKER_PATH),
            "--labels-json",
            json.dumps(labels),
            "--title",
            title,
            "--head-ref",
            head_ref,
            "--author-login",
            author_login,
            "--head-repository",
            head_repository,
            "--repository",
            "opsmill/example",
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_release_label_contract() -> None:
    assert CONFIG_PATH.read_text() == CANONICAL_CONFIG

    declared_labels = LABELS_PATH.read_text()
    for label in ("changes/major", "changes/minor", "changes/patch"):
        assert f'name: "{label}"' in declared_labels

        accepted = run_checker([label, "type/housekeeping"])
        assert accepted.returncode == 0, accepted.stderr
        assert label in accepted.stdout

    for labels in ([], ["type/bug"], ["changes/patch", "changes/minor"]):
        rejected = run_checker(labels)
        assert rejected.returncode != 0
        assert "exactly one" in rejected.stderr

    spoofed_release_pr = run_checker([], title="chore(release): v1.2.3", head_ref="release/v1.2.3")
    assert spoofed_release_pr.returncode != 0
    assert "exactly one" in spoofed_release_pr.stderr

    forked_bot_release_pr = run_checker(
        [], title="chore(release): v1.2.3", head_ref="release/v1.2.3", author_login="opsmill-bot"
    )
    assert forked_bot_release_pr.returncode != 0
    assert "exactly one" in forked_bot_release_pr.stderr

    release_pr = run_checker(
        [],
        title="chore(release): v1.2.3",
        head_ref="release/v1.2.3",
        author_login="opsmill-bot",
        head_repository="opsmill/example",
    )
    assert release_pr.returncode == 0, release_pr.stderr
    assert "generated release pull request" in release_pr.stdout

    edited_release_pr = run_checker(
        [],
        title="chore(release): v1.2.3 [hold]",
        head_ref="release/v1.2.3",
        author_login="opsmill-bot",
        head_repository="opsmill/example",
    )
    assert edited_release_pr.returncode == 0, edited_release_pr.stderr

    bot_dependency_pr = run_checker(
        [],
        title="update Infrahub to version 1.11.4 against stable",
        head_ref="stable-1.11.4",
        author_login="opsmill-bot",
        head_repository="opsmill/example",
    )
    assert bot_dependency_pr.returncode != 0
    assert "exactly one" in bot_dependency_pr.stderr

    for head_ref in ("release/v1.2.3rc1", "release/v1.2.3.post1"):
        accepted_branch = run_checker(
            [],
            title="chore(release): v1.2.3",
            head_ref=head_ref,
            author_login="opsmill-bot",
            head_repository="opsmill/example",
        )
        assert accepted_branch.returncode == 0, head_ref

    for head_ref in ("release/vnext", "release/v1.2", "release/v1.2.3-hotfix", "release/v1.2.3/extra"):
        rejected_branch = run_checker(
            [],
            title="chore(release): v1.2.3",
            head_ref=head_ref,
            author_login="opsmill-bot",
            head_repository="opsmill/example",
        )
        assert rejected_branch.returncode != 0, head_ref

    mismatched_title = run_checker(
        [],
        title="fix: chore(release): v1.2.3",
        head_ref="release/v1.2.3",
        author_login="opsmill-bot",
        head_repository="opsmill/example",
    )
    assert mismatched_title.returncode != 0


def test_gate_never_runs_pull_request_code() -> None:
    """The gate runs from the base branch and must not check out the PR head."""
    lines = [line.strip() for line in (WORKFLOWS_PATH / "release-label-check.yml").read_text().splitlines()]
    assert "pull_request_target:" in lines
    assert "pull_request:" not in lines
    assert "persist-credentials: false" in lines
    assert not [line for line in lines if line.startswith("ref:")]
    assert [line for line in lines if line.startswith(("contents:", "pull-requests:", "actions:", "id-token:"))] == [
        "contents: read"
    ]


def test_dependabot_pull_requests_carry_a_bump_label() -> None:
    updates = DEPENDABOT_PATH.read_text().split("\n  - package-ecosystem:")[1:]
    assert updates
    for update in updates:
        labels = [line.strip() for line in update.splitlines()]
        assert '- "changes/patch"' in labels, update.splitlines()[0]


def test_bot_pull_requests_carry_a_bump_label() -> None:
    """Every workflow that opens a non-release PR must label it, or the gate blocks it."""
    for workflow in ("update-infrahub.yml", "update-infrahub-sdk.yml", "version-sync.yml"):
        content = (WORKFLOWS_PATH / workflow).read_text()
        assert "gh pr create" in content
        assert '--label "changes/patch"' in content, workflow


def test_exemption_matches_the_release_pr_generator() -> None:
    """The exemption must accept exactly what auto-bump.yml opens, or every release PR is blocked."""
    generator = (WORKFLOWS_PATH / "auto-bump.yml").read_text()
    branch = re.search(r'export BRANCH="([^"$]*)\$\{VERSION\}"', generator)
    title = re.search(r'--title "([^"$]*)\$\{VERSION\}"', generator)
    assert branch, "auto-bump.yml no longer sets BRANCH from VERSION"
    assert title, "auto-bump.yml no longer sets the release PR title from VERSION"

    for version in ("1.2.3", "1.2.3rc1", "1.2.3.post1"):
        generated = run_checker(
            [],
            title=f"{title.group(1)}{version}",
            head_ref=f"{branch.group(1)}{version}",
            author_login="opsmill-bot",
            head_repository="opsmill/example",
        )
        assert generated.returncode == 0, (branch.group(1), version, generated.stderr)
