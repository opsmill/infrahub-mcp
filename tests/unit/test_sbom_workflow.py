"""Keep the SBOM smoke test on the same installer as the release workflow."""

from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).parents[2] / ".github" / "workflows"


def test_sbom_smoke_uses_release_syft_installer() -> None:
    """A passing smoke test must validate the action version shipped by releases."""
    release = yaml.safe_load((WORKFLOWS / "ci-docker-image.yml").read_text())
    smoke = yaml.safe_load((WORKFLOWS / "ci-sbom.yml").read_text())
    release_installers = [
        step["uses"]
        for step in release["jobs"]["sbom"]["steps"]
        if step.get("uses", "").startswith("anchore/sbom-action/download-syft@")
    ]
    smoke_installers = [
        step["uses"]
        for step in smoke["jobs"]["sbom-smoke"]["steps"]
        if step.get("uses", "").startswith("anchore/sbom-action/download-syft@")
    ]
    assert len(release_installers) == 1
    assert smoke_installers == release_installers
