"""Regression coverage for release workflow boundaries and release bodies."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def workflow_events(workflow_text: str) -> set[str]:
    """Return the event names a GitHub Actions workflow triggers on.

    Accepts every trigger form GitHub supports: a single string (``on: push``),
    a list (``on: [push, pull_request]``) or a mapping of events to filters.
    PyYAML follows YAML 1.1 and loads a bare ``on`` key as boolean ``True``, so
    both spellings are looked up.
    """
    workflow = yaml.safe_load(workflow_text)
    triggers = workflow.get("on", workflow.get(True))
    if isinstance(triggers, str):
        return {triggers}
    if isinstance(triggers, list):
        return {str(event) for event in triggers}
    if isinstance(triggers, dict):
        return {str(event) for event in triggers}
    return set()


def test_release_pipeline_uses_branch_ci_and_curated_notes() -> None:
    """General CI keeps running on base-branch pushes and releases publish curated notes."""
    ci_workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    publish_workflow = (ROOT / ".github/workflows/release-publish.yml").read_text()
    renderer = ROOT / "scripts/release_body.py"

    problems: list[str] = []
    # Pushes to ``stable`` refresh the dependency caches that pull requests can
    # only read from their base branch.
    if not {"pull_request", "push"} <= workflow_events(ci_workflow):
        problems.append("general CI must run on pull requests and base-branch pushes")
    if not renderer.is_file():
        problems.append("the curated release-notes renderer is missing")
    if "scripts/release_body.py" not in publish_workflow:
        problems.append("the publisher does not use the curated release-notes renderer")

    assert not problems, "; ".join(problems)
