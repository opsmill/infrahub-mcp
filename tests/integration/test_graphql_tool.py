"""Integration: `query_graphql` reads seeded data and rejects mutations (contract T3, FR-005; Constitution I/VI)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from fastmcp.exceptions import ToolError
from mcp import McpError

from tests.integration._util import tool_text

if TYPE_CHECKING:
    from fastmcp import Client

pytestmark = [pytest.mark.integration]

_WIDGET_QUERY = "query { TestingWidget { edges { node { name { value } } } } }"
_MUTATION = 'mutation { CoreAccountCreate(data: {name: {value: "x"}}) { ok } }'


async def test_query_graphql_reads_seeded_data(mcp_client: Client) -> None:
    result = await mcp_client.call_tool("query_graphql", {"query": _WIDGET_QUERY})

    assert not result.is_error
    assert "alpha" in tool_text(result)


async def test_query_graphql_rejects_mutation(mcp_client: Client) -> None:
    # The read-only GraphQL tool rejects mutations via AST inspection (OperationType.MUTATION).
    with pytest.raises((ToolError, McpError)):
        await mcp_client.call_tool("query_graphql", {"query": _MUTATION})
