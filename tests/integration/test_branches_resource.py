"""Integration: the `infrahub://branches` resource lists main + the per-test branch (contract R2, FR-005)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.integration._util import resource_json

if TYPE_CHECKING:
    from fastmcp import Client

pytestmark = [pytest.mark.integration]


async def test_branches_resource_includes_main_and_test_branch(
    mcp_client: Client,
    test_branch: str,
) -> None:
    contents = await mcp_client.read_resource("infrahub://branches")
    branches = resource_json(contents)  # {branch_name: {is_default: bool, description: str}}

    assert "main" in branches
    assert test_branch in branches
    assert branches["main"]["is_default"] is True
