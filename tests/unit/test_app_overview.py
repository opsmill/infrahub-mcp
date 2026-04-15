"""Tests for the overview tool (overview.py)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Context
from prefab_ui.app import PrefabApp

from infrahub_app.overview import fetch_overview_data, overview


def _make_ctx(client: AsyncMock | None = None) -> MagicMock:
    """Create a mock MCP Context with AppContext."""
    ctx = MagicMock(spec=Context)
    app_ctx = MagicMock()
    app_ctx.client = client or AsyncMock()
    ctx.request_context.lifespan_context = app_ctx
    return ctx


_FAKE_CATALOG = [
    {"kind": "InfraDevice", "namespace": "Infra", "label": "Device", "attr_count": 5, "rel_count": 3},
    {"kind": "InfraPlatform", "namespace": "Infra", "label": "Platform", "attr_count": 2, "rel_count": 1},
    {"kind": "CoreAccount", "namespace": "Core", "label": "Account", "attr_count": 4, "rel_count": 2},
]

_FAKE_COUNTS = [
    {"kind": "InfraDevice", "label": "Device", "count": 30},
    {"kind": "InfraPlatform", "label": "Platform", "count": 5},
    {"kind": "CoreAccount", "label": "Account", "count": 0},
]

_FAKE_SCHEMA_DETAIL: dict[str, Any] = {
    "kind": "InfraDevice",
    "attributes": [{"name": "name", "kind": "Text", "optional": False}],
    "relationships": [{"name": "platform", "peer": "InfraPlatform", "cardinality": "one"}],
}


class TestFetchOverviewData:
    @patch("infrahub_app.overview._fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    @patch("infrahub_app.overview._fetch_node_counts", return_value=_FAKE_COUNTS)
    @patch("infrahub_app.overview._fetch_schema_catalog", return_value=_FAKE_CATALOG)
    async def test_returns_expected_keys(
        self, mock_catalog: MagicMock, mock_counts: MagicMock, mock_detail: MagicMock,
    ) -> None:
        ctx = _make_ctx()
        result = await fetch_overview_data(ctx=ctx)
        assert "catalog" in result
        assert "counts" in result
        assert "namespace_data" in result
        assert "complexity_data" in result
        assert "mermaid_str" in result

    @patch("infrahub_app.overview._fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    @patch("infrahub_app.overview._fetch_node_counts", return_value=_FAKE_COUNTS)
    @patch("infrahub_app.overview._fetch_schema_catalog", return_value=_FAKE_CATALOG)
    async def test_namespace_data_groups_correctly(
        self, mock_catalog: MagicMock, mock_counts: MagicMock, mock_detail: MagicMock,
    ) -> None:
        ctx = _make_ctx()
        result = await fetch_overview_data(ctx=ctx)
        ns_names = {d["name"] for d in result["namespace_data"]}
        assert "Infra" in ns_names
        assert "Core" in ns_names

    @patch("infrahub_app.overview._fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    @patch("infrahub_app.overview._fetch_node_counts", return_value=_FAKE_COUNTS)
    @patch("infrahub_app.overview._fetch_schema_catalog", return_value=_FAKE_CATALOG)
    async def test_complexity_excludes_builtins(
        self, mock_catalog: MagicMock, mock_counts: MagicMock, mock_detail: MagicMock,
    ) -> None:
        ctx = _make_ctx()
        result = await fetch_overview_data(ctx=ctx)
        labels = [c["label"] for c in result["complexity_data"]]
        assert "Account" not in labels
        assert "Device" in labels


class TestOverviewUI:
    @patch("infrahub_app.overview._fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    @patch("infrahub_app.overview._fetch_node_counts", return_value=_FAKE_COUNTS)
    @patch("infrahub_app.overview._fetch_schema_catalog", return_value=_FAKE_CATALOG)
    async def test_returns_prefab_app(
        self, mock_catalog: MagicMock, mock_counts: MagicMock, mock_detail: MagicMock,
    ) -> None:
        ctx = _make_ctx()
        result = await overview(ctx=ctx)
        assert isinstance(result, PrefabApp)

    @patch("infrahub_app.overview._fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    @patch("infrahub_app.overview._fetch_node_counts", return_value=_FAKE_COUNTS)
    @patch("infrahub_app.overview._fetch_schema_catalog", return_value=_FAKE_CATALOG)
    async def test_has_correct_title(
        self, mock_catalog: MagicMock, mock_counts: MagicMock, mock_detail: MagicMock,
    ) -> None:
        ctx = _make_ctx()
        result = await overview(ctx=ctx)
        assert result.title == "Overview"  # type: ignore[attr-defined]

    @patch("infrahub_app.overview._fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    @patch("infrahub_app.overview._fetch_node_counts", return_value=_FAKE_COUNTS)
    @patch("infrahub_app.overview._fetch_schema_catalog", return_value=_FAKE_CATALOG)
    async def test_state_has_correct_totals(
        self, mock_catalog: MagicMock, mock_counts: MagicMock, mock_detail: MagicMock,
    ) -> None:
        ctx = _make_ctx()
        result = await overview(ctx=ctx)
        assert result.state["total_nodes"] == 35  # type: ignore[attr-defined]
        assert result.state["populated_count"] == 2  # type: ignore[attr-defined]
        assert result.state["empty_count"] == 1  # type: ignore[attr-defined]

    @patch("infrahub_app.overview._fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    @patch("infrahub_app.overview._fetch_node_counts", return_value=_FAKE_COUNTS)
    @patch("infrahub_app.overview._fetch_schema_catalog", return_value=_FAKE_CATALOG)
    async def test_with_namespace_filter(
        self, mock_catalog: MagicMock, mock_counts: MagicMock, mock_detail: MagicMock,
    ) -> None:
        ctx = _make_ctx()
        result = await overview(ctx=ctx, filters={"namespace": "Infra"})
        assert isinstance(result, PrefabApp)

    @patch("infrahub_app.overview._fetch_schema_catalog", side_effect=Exception("Connection refused"))
    async def test_raises_on_error(self, mock_catalog: MagicMock) -> None:
        ctx = _make_ctx()
        with pytest.raises(Exception, match="Connection refused"):
            await overview(ctx=ctx)
