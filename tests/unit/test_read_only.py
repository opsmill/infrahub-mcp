"""Exercise the real GraphQL read tool's parser and SDK boundary."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from infrahub_mcp.tools.gql import query_graphql


@pytest.mark.parametrize(
    "query",
    [
        "mutation { createNode { id } }",
        "mutation CreateNode { createNode { id } }",
        "  \n  mutation { createNode { id } }",
        "# Read-only request\n# Another comment\nmutation { createNode { id } }",
        "fragment NodeFields on Node { id } mutation { createNode { ...NodeFields } }",
        "query GetNodes { allNodes { id } } mutation Delete { deleteNode { id } }",
        "mutation Delete { deleteNode { id } } query GetNodes { allNodes { id } }",
    ],
    ids=["anonymous", "named", "whitespace", "comments", "fragment-first", "mutation-last", "mutation-first"],
)
async def test_query_rejects_mutations_before_accessing_sdk(query: str) -> None:
    """No operation in a mixed or comment-prefixed document can bypass the read guard."""
    with patch("infrahub_mcp.tools.gql.get_client") as get_client:
        with pytest.raises(ToolError, match="Mutations are not allowed"):
            await query_graphql(ctx=MagicMock(), query=query)

    get_client.assert_not_called()


@pytest.mark.parametrize("query", ["", "# comment only", "{{{invalid", "query { allNodes( }"])
async def test_query_reports_invalid_syntax_before_accessing_sdk(query: str) -> None:
    with patch("infrahub_mcp.tools.gql.get_client") as get_client:
        with pytest.raises(ToolError, match="Invalid GraphQL syntax"):
            await query_graphql(ctx=MagicMock(), query=query)

    get_client.assert_not_called()


@pytest.mark.parametrize(
    "query",
    [
        "{ allNodes { id } }",
        "query Named { allNodes { id } }",
        "# mutation is just a comment\nquery { allNodes { id } }",
        "fragment NodeFields on Node { id } query { allNodes { ...NodeFields } }",
        'query { mutation_log(filter: "mutation { createNode }") { id } }',
    ],
    ids=["shorthand", "named", "comment", "fragment", "mutation-in-string-and-field"],
)
@pytest.mark.parametrize("branch", [None, "candidate"])
async def test_query_forwards_valid_document_and_branch_unchanged(query: str, branch: str | None) -> None:
    expected = {"allNodes": [{"id": "node-1"}]}
    client = MagicMock()
    client.execute_graphql = AsyncMock(return_value=expected)

    with patch("infrahub_mcp.tools.gql.get_client", return_value=client):
        result = await query_graphql(ctx=MagicMock(), query=query, branch=branch)

    assert result == expected
    client.execute_graphql.assert_awaited_once_with(query=query, branch_name=branch)
