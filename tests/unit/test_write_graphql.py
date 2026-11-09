"""Exercise GraphQL write validation before session creation and SDK execution."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from infrahub_mcp.tools.write import mutate_graphql


@pytest.mark.parametrize(
    ("query", "error"),
    [
        ("# A comment\nquery { CoreTag { edges { node { id } } } }", "only accepts GraphQL mutations"),
        ("subscription { changed { id } }", "only accepts GraphQL mutations"),
        ("mutation { CoreTagCreate { ok } } query { CoreTag { edges { node { id } } } }", "only accepts"),
        ('# A comment\nmutation { alias: BranchMerge(data: {name: "main"}) { ok } }', "not allowed"),
        ('mutation { ... on Mutation { alias: BranchDelete(data: {name: "main"}) { ok } } }', "not allowed"),
        (
            "fragment Hidden on Mutation { alias: SchemaEnumRemove(data: {}) { ok } } mutation { ...Hidden }",
            "not allowed",
        ),
        ("mutation { broken(", "Invalid GraphQL syntax"),
        ("# comment only", "Invalid GraphQL syntax"),
    ],
    ids=[
        "query",
        "subscription",
        "mixed-operations",
        "comment-and-alias",
        "inline-fragment",
        "named-fragment",
        "syntax",
        "comment-only",
    ],
)
async def test_invalid_mutation_has_no_sdk_or_session_side_effects(query: str, error: str) -> None:
    with (
        patch("infrahub_mcp.tools.write.get_client") as get_client,
        patch("infrahub_mcp.tools.write.get_or_create_session_branch", new_callable=AsyncMock) as session_branch,
    ):
        with pytest.raises(ToolError, match=error):
            await mutate_graphql(ctx=MagicMock(), query=query)

    get_client.assert_not_called()
    session_branch.assert_not_awaited()


@pytest.mark.parametrize(
    "query",
    [
        'mutation { CoreTagCreate(data: {name: {value: "web"}}) { ok } }',
        '# BranchMerge is a comment\nmutation { CoreTagCreate(data: {name: {value: "BranchDelete"}}) { ok } }',
        'fragment Result on CreateResult { ok } mutation { CoreTagCreate(data: {name: {value: "web"}}) { ...Result } }',
    ],
    ids=["ordinary", "blocked-names-in-comment-and-string", "fragment-first"],
)
async def test_valid_mutation_uses_session_branch_and_preserves_document(query: str) -> None:
    expected = {"CoreTagCreate": {"ok": True}}
    client = MagicMock()
    client.execute_graphql = AsyncMock(return_value=expected)
    ctx = MagicMock()

    with (
        patch("infrahub_mcp.tools.write.get_client", return_value=client),
        patch("infrahub_mcp.tools.write.get_or_create_session_branch", new_callable=AsyncMock) as session_branch,
    ):
        session_branch.return_value = "mcp/session-test"
        result = await mutate_graphql(ctx=ctx, query=query)

    assert result == expected
    session_branch.assert_awaited_once_with(ctx)
    client.execute_graphql.assert_awaited_once_with(query=query, branch_name="mcp/session-test")
