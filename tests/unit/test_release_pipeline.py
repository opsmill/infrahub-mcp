"""Regression coverage for release workflow boundaries and release bodies."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_release_pipeline_uses_pr_ci_and_curated_notes() -> None:
    """Release merges should publish curated notes without rerunning general CI."""
    ci_workflow = (ROOT / ".github/workflows/ci.yml").read_text()
    publish_workflow = (ROOT / ".github/workflows/release-publish.yml").read_text()
    renderer = ROOT / "scripts/release_body.py"
    trigger_block = ci_workflow.split("concurrency:", maxsplit=1)[0]

    problems: list[str] = []
    if "\n  push:" in trigger_block:
        problems.append("general CI still runs on post-merge pushes")
    if not renderer.is_file():
        problems.append("the curated release-notes renderer is missing")
    if "scripts/release_body.py" not in publish_workflow:
        problems.append("the publisher does not use the curated release-notes renderer")

    assert not problems, "; ".join(problems)
