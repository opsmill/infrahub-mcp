"""Integration: cross-cutting failure-mode contracts (F1/F2, FR-012; Constitution VI).

F2 (malformed input rejected by FastMCP schema enforcement before any SDK call) is
asserted directly. The full F1 scenario (Infrahub torn down mid-suite) is destructive
to the shared session container, so here we assert the weaker, non-destructive property
that a bad request surfaces as a clean MCP error with no internal stack trace leaked;
the full unreachable-backend case is validated manually (see quickstart.md).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastmcp.exceptions import ToolError
from mcp import McpError

from tests.integration._util import tool_text

if TYPE_CHECKING:
    from fastmcp import Client

pytestmark = [pytest.mark.integration]


async def test_malformed_input_rejected_before_sdk_call(mcp_client: Client) -> None:
    # `get_nodes` requires `kind`; omitting it must be rejected by schema enforcement (F2).
    with pytest.raises((ToolError, McpError)):
        await mcp_client.call_tool("get_nodes", {})


async def test_bad_request_surfaces_clean_error(mcp_client: Client) -> None:
    # An unknown kind must surface a clean message, never an internal traceback (F1, Principle VI).
    # raise_on_error=False so an error result is returned (not raised) for inspection.
    result = await mcp_client.call_tool(
        "get_nodes",
        {"kind": "ThisKindDoesNotExist"},
        raise_on_error=False,
    )

    assert "Traceback (most recent call last)" not in tool_text(result)
