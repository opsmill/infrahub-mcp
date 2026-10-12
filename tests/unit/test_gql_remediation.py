"""query_graphql remediation when Infrahub rejects a ``filters`` argument (spec FR-016, SC-006)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Client
from infrahub_sdk.exceptions import GraphQLError

import infrahub_mcp.tools.gql as gql_module
from infrahub_mcp.tools.gql import mcp


async def _error_text(query: str, message: str) -> str:
    client = MagicMock()
    client.execute_graphql = AsyncMock(side_effect=GraphQLError(errors=[{"message": message}], query=query))
    with patch.object(gql_module, "get_client", return_value=client):
        async with Client(mcp) as mcp_client:
            result = await mcp_client.call_tool("query_graphql", {"query": query}, raise_on_error=False)
    assert result.is_error
    return result.content[0].text  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("query", "kind"),
    [
        ('{ LocationSite(filters: {name__value: "x"}) { count } }', "LocationSite"),
        ('query Sites { DcimDevice(filters: {role__value: "edge"}) { count } }', "DcimDevice"),
    ],
)
async def test_filters_argument_gets_the_correct_form(query: str, kind: str) -> None:
    text = await _error_text(query, f"Unknown argument 'filters' on field 'Query.{kind}'.")
    assert 'no "filters" argument' in text
    assert f"{kind}(name__value:" in text
    assert f'get_schema(kind="{kind}")' in text


async def test_filters_argument_without_a_top_level_field_uses_an_example_kind() -> None:
    text = await _error_text("{ __typename }", "Unknown argument 'filters' on field 'Query.Something'.")
    assert "DcimDevice(name__value:" in text


async def test_other_errors_keep_the_schema_remediation() -> None:
    text = await _error_text("{ LocationSite { count } }", "Cannot query field 'nope' on type 'LocationSite'.")
    assert "get_schema()" in text
    assert 'no "filters" argument' not in text
