"""Integration: a representative write tool — branch isolation + read-only gating (contract T4, FR-005; Constitution III/VI)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastmcp.exceptions import ToolError
from mcp import McpError

if TYPE_CHECKING:
    from fastmcp import Client
    from infrahub_sdk import InfrahubClient

pytestmark = [pytest.mark.integration]


async def test_node_upsert_does_not_touch_main(
    mcp_client: Client,
    infrahub_client: InfrahubClient,
    seeded_infrahub: dict[str, object],
) -> None:
    kind = str(seeded_infrahub["widget_kind"])

    result = await mcp_client.call_tool(
        "node_upsert",
        {"kind": kind, "data": {"name": "delta", "color": "green"}},
    )
    assert not result.is_error

    # Branch-safety (Principle III): the write lands on the server's session branch,
    # NOT on main. NOTE(runtime): confirm node_upsert's session-branch behavior + result shape.
    on_main = await infrahub_client.filters(kind=kind, name__value="delta", branch="main")
    assert on_main == []


async def test_write_tool_blocked_in_read_only(mcp_client_readonly: Client) -> None:
    kind = "TestingWidget"

    # With read_only=true, write tools are unmounted and ReadOnlyMiddleware blocks the
    # call — either way the in-process client raises rather than mutating data.
    with pytest.raises((ToolError, McpError)):
        await mcp_client_readonly.call_tool(
            "node_upsert",
            {"kind": kind, "data": {"name": "epsilon", "color": "black"}},
        )
