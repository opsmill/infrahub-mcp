"""Unit tests for get_nodes pagination edge cases.

These tests mock out Infrahub interactions so they run without a live server.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infrahub_mcp.tools.nodes import get_nodes


def _make_ctx() -> MagicMock:
    """Context stub with the async hooks get_nodes calls."""
    ctx = MagicMock()
    ctx.request_id = "req-test"
    ctx.info = AsyncMock()
    ctx.debug = AsyncMock()
    ctx.report_progress = AsyncMock()
    return ctx


def _make_node(label: str) -> MagicMock:
    node = MagicMock()
    node.display_label = label
    return node


@pytest.mark.asyncio
async def test_has_more_is_none_when_total_count_unavailable() -> None:
    """When `_get_total_count` fails (returns -1), `has_more` must be None.

    This prevents clients from mistaking an exact-page-boundary response for
    "more results available" when the count query itself failed.
    """
    ctx = _make_ctx()

    mock_client = MagicMock()
    mock_schema = MagicMock(kind="LocationSite")

    fake_nodes = [_make_node("a"), _make_node("b")]

    with (
        patch("infrahub_mcp.tools.nodes.get_client", return_value=mock_client),
        patch("infrahub_mcp.tools.nodes.get_cached_kind", AsyncMock(return_value=mock_schema)),
    ):
        with patch("infrahub_mcp.tools.nodes._get_total_count", AsyncMock(return_value=-1)):
            with patch("infrahub_mcp.tools.nodes._fetch_nodes", AsyncMock(return_value=fake_nodes)):
                result = await get_nodes(ctx=ctx, kind="LocationSite")

    assert result["has_more"] is None
    assert result["total_count"] == -1
    assert result["count"] == 2


@pytest.mark.asyncio
async def test_has_more_true_when_more_pages_available() -> None:
    """`has_more` is True when the total count exceeds offset + page size."""
    ctx = _make_ctx()

    mock_client = MagicMock()
    mock_schema = MagicMock(kind="LocationSite")

    fake_nodes = [_make_node("a"), _make_node("b")]

    with (
        patch("infrahub_mcp.tools.nodes.get_client", return_value=mock_client),
        patch("infrahub_mcp.tools.nodes.get_cached_kind", AsyncMock(return_value=mock_schema)),
    ):
        with patch("infrahub_mcp.tools.nodes._get_total_count", AsyncMock(return_value=10)):
            with patch("infrahub_mcp.tools.nodes._fetch_nodes", AsyncMock(return_value=fake_nodes)):
                result = await get_nodes(ctx=ctx, kind="LocationSite", limit=2, offset=0)

    assert result["has_more"] is True
    assert result["total_count"] == 10


@pytest.mark.asyncio
async def test_has_more_false_on_exact_page_boundary() -> None:
    """`has_more` is False when offset + returned nodes equal total_count."""
    ctx = _make_ctx()

    mock_client = MagicMock()
    mock_schema = MagicMock(kind="LocationSite")

    fake_nodes = [_make_node("a"), _make_node("b")]

    with (
        patch("infrahub_mcp.tools.nodes.get_client", return_value=mock_client),
        patch("infrahub_mcp.tools.nodes.get_cached_kind", AsyncMock(return_value=mock_schema)),
    ):
        with patch("infrahub_mcp.tools.nodes._get_total_count", AsyncMock(return_value=4)):
            with patch("infrahub_mcp.tools.nodes._fetch_nodes", AsyncMock(return_value=fake_nodes)):
                result = await get_nodes(ctx=ctx, kind="LocationSite", limit=2, offset=2)

    assert result["has_more"] is False
    assert result["total_count"] == 4
