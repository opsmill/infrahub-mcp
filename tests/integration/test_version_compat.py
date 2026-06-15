"""Integration: Infrahub version-compatibility check (contract V1, FR-013; "version drift" edge case).

Emits a distinct, clearly-labeled result (xfail) when the running Infrahub version
diverges from the version the pinned infrahub-sdk targets — so version drift is
never confused with a functional product regression.
"""

from __future__ import annotations

from importlib.metadata import version as pkg_version
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClient

pytestmark = [pytest.mark.integration]


def _minor(version: str) -> str:
    """Return the MAJOR.MINOR prefix of a version string."""
    return ".".join(version.lstrip("v").split(".")[:2])


async def test_running_infrahub_matches_sdk_version(infrahub_client: InfrahubClient) -> None:
    running = await infrahub_client.get_version()
    sdk = pkg_version("infrahub-sdk")

    # NOTE(runtime): "supported range" heuristic = matching MAJOR.MINOR (research D11).
    if _minor(running) != _minor(sdk):
        pytest.xfail(
            f"Infrahub version drift: running Infrahub {running} vs infrahub-sdk {sdk} "
            "(version drift, NOT a product regression — reconcile the pinned versions)."
        )

    assert _minor(running) == _minor(sdk)
