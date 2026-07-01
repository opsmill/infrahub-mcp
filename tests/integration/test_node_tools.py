"""Integration: node read tools `get_nodes` — list, filter, pagination (contracts T1/T2, FR-005)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from tests.integration._util import tool_text

if TYPE_CHECKING:
    from fastmcp import Client

pytestmark = [pytest.mark.integration]


async def test_get_nodes_returns_seeded_widgets(
    mcp_client: Client,
    seeded_infrahub: dict[str, object],
) -> None:
    result = await mcp_client.call_tool("get_nodes", {"kind": seeded_infrahub["widget_kind"]})

    assert not result.is_error
    text = tool_text(result)
    assert "alpha" in text
    assert "gamma" in text


async def test_get_nodes_filter_by_color(
    mcp_client: Client,
    seeded_infrahub: dict[str, object],
) -> None:
    # NOTE(runtime): confirm the tool forwards `filters` to the SDK as `<attr>__value`.
    result = await mcp_client.call_tool(
        "get_nodes",
        {"kind": seeded_infrahub["widget_kind"], "filters": {"color__value": "blue"}},
    )

    assert not result.is_error
    text = tool_text(result)
    assert "beta" in text  # the only blue widget
    assert "alpha" not in text


async def test_get_nodes_pagination_limits_page_size(
    mcp_client: Client,
    seeded_infrahub: dict[str, object],
) -> None:
    # Three widgets are seeded; a limit of 2 must return a partial first page.
    # NOTE(runtime): confirm pagination metadata shape to assert "has next page".
    page = await mcp_client.call_tool(
        "get_nodes",
        {"kind": seeded_infrahub["widget_kind"], "limit": 2},
    )

    assert not page.is_error
    text = tool_text(page)
    present = [name for name in ("alpha", "beta", "gamma") if name in text]
    assert len(present) == 2
