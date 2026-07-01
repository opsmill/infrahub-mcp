"""Integration: Infrahub version-compatibility check (contract V1, FR-013).

Asserts the running Infrahub server matches the container image the test harness
actually launched — ``INFRAHUB_TESTING_IMAGE_VER`` when set, otherwise the
``infrahub-testcontainers`` package version that pins the default image (mirrors
the resolution in ``conftest.py``).

This guards a real, controllable invariant — that we exercised the server version
we intended to — rather than the ``infrahub-sdk`` package version, which tracks
independently of the Infrahub server release line (SDK 1.20.x vs server 1.10.x)
and so would never match.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest
from infrahub_testcontainers import __version__ as testcontainers_version

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClient

pytestmark = [pytest.mark.integration]


def _minor(version: str) -> str:
    """Return the MAJOR.MINOR prefix of a version string."""
    return ".".join(version.lstrip("v").split(".")[:2])


async def test_running_infrahub_matches_launched_image(infrahub_client: InfrahubClient) -> None:
    running = await infrahub_client.get_version()
    # The image the harness launched: explicit override, else the infrahub-testcontainers
    # package version — the exact resolution conftest.py uses to pick the image tag.
    expected = os.getenv("INFRAHUB_TESTING_IMAGE_VER") or testcontainers_version

    assert _minor(running) == _minor(expected), (
        f"Running Infrahub {running} does not match the launched image {expected} "
        "(MAJOR.MINOR mismatch — the container did not start at the requested version)."
    )
