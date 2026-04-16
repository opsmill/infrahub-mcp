"""Tests for the explore tool (explore.py)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Context
from fastmcp.apps import FastMCPApp
from fastmcp.exceptions import ToolError
from prefab_ui.app import PrefabApp

from infrahub_app import app
from infrahub_app.explore import explore, fetch_explore_data


def _make_ctx(client: AsyncMock | None = None) -> MagicMock:
    """Create a mock MCP Context with AppContext."""
    ctx = MagicMock(spec=Context)
    app_ctx = MagicMock()
    app_ctx.client = client or AsyncMock()
    ctx.request_context.lifespan_context = app_ctx
    return ctx


def _make_mock_schema_obj(kind: str, label: str | None = None) -> MagicMock:
    """Create a mock schema object for client.schema.all() results."""
    obj = MagicMock()
    obj.kind = kind
    obj.label = label
    obj.attributes = []
    obj.relationships = []
    return obj


def _make_client_with_schemas() -> AsyncMock:
    """Create a mock client that returns schemas for .all() calls."""
    client = AsyncMock()
    client.schema.all.return_value = {
        "InfraDevice": _make_mock_schema_obj("InfraDevice", "Device"),
        "InfraPlatform": _make_mock_schema_obj("InfraPlatform", "Platform"),
        "LocationSite": _make_mock_schema_obj("LocationSite", "Site"),
    }
    return client


def test_app_is_fastmcp_app() -> None:
    assert isinstance(app, FastMCPApp)
    assert app.name == "Infrahub"


_FAKE_SCHEMA_DETAIL: dict[str, Any] = {
    "kind": "InfraDevice",
    "attributes": [
        {"name": "name", "kind": "Text", "optional": False},
        {"name": "status", "kind": "Dropdown", "optional": False},
    ],
    "relationships": [
        {"name": "platform", "peer": "InfraPlatform", "cardinality": "one"},
    ],
}

_FAKE_STATE: dict[str, Any] = {
    "node_count": 3,
    "attr_count": 2,
    "rel_count": 1,
    "pie_panels": [{"field": "status", "type": "pie", "data": [{"name": "active", "count": 2}]}],
    "bar_panels": [],
    "table_rows": [
        {"name": "device-1", "status": "active", "platform": "Juniper"},
        {"name": "device-2", "status": "active", "platform": "Cisco"},
        {"name": "device-3", "status": "decommissioned", "platform": "Juniper"},
    ],
}

_FAKE_COLUMNS = ["name", "status", "platform"]


class TestFetchExploreData:
    @patch("infrahub_app.explore._build_explore_state", return_value=_FAKE_STATE)
    @patch("infrahub_app.explore._validate_kind", return_value="InfraDevice")
    async def test_returns_ui_state(
        self, mock_validate: MagicMock, mock_build: MagicMock,
    ) -> None:
        ctx = _make_ctx()
        result = await fetch_explore_data(kind="InfraDevice", ctx=ctx)
        assert "node_count" in result
        assert "pie_panels" in result
        assert "bar_panels" in result
        assert "table_rows" in result


class TestExploreUI:
    @patch("infrahub_app.explore._fetch_nodes_for_kind", return_value=([], _FAKE_COLUMNS))
    @patch("infrahub_app.explore._fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    @patch("infrahub_app.explore._build_explore_state", return_value=_FAKE_STATE)
    @patch("infrahub_app.explore._validate_kind", return_value="InfraDevice")
    async def test_returns_prefab_app_with_kind(
        self,
        mock_validate: MagicMock,
        mock_build: MagicMock,
        mock_schema: MagicMock,
        mock_nodes: MagicMock,
    ) -> None:
        ctx = _make_ctx(_make_client_with_schemas())
        result = await explore(kind="InfraDevice", ctx=ctx)
        assert isinstance(result, PrefabApp)
        assert result.title == "Explore: InfraDevice"  # type: ignore[attr-defined]

    @patch("infrahub_app.explore._build_explore_state", return_value=_FAKE_STATE)
    @patch("infrahub_app.explore._validate_kind", return_value="InfraDevice")
    @patch("infrahub_app.explore._fetch_nodes_for_kind", return_value=([], _FAKE_COLUMNS))
    @patch("infrahub_app.explore._fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    async def test_state_has_node_count(
        self,
        mock_schema: MagicMock,
        mock_nodes: MagicMock,
        mock_validate: MagicMock,
        mock_build: MagicMock,
    ) -> None:
        ctx = _make_ctx(_make_client_with_schemas())
        result = await explore(kind="InfraDevice", ctx=ctx)
        assert result.state["node_count"] == 3  # type: ignore[attr-defined]

    async def test_works_without_kind(self) -> None:
        ctx = _make_ctx(_make_client_with_schemas())
        result = await explore(ctx=ctx)
        assert isinstance(result, PrefabApp)
        assert result.title == "Explore"  # type: ignore[attr-defined]
        assert result.state["node_count"] == 0  # type: ignore[attr-defined]
        assert result.state["selected_kind"] == ""  # type: ignore[attr-defined]

    async def test_combobox_populated_with_kinds(self) -> None:
        ctx = _make_ctx(_make_client_with_schemas())
        result = await explore(ctx=ctx)
        # State should contain the selected_kind key for Combobox binding
        assert "selected_kind" in result.state  # type: ignore[attr-defined]

    @patch("infrahub_app.explore._validate_kind", side_effect=ToolError("Kind 'BadKind' not found."))
    async def test_raises_on_invalid_kind(self, mock_validate: MagicMock) -> None:
        ctx = _make_ctx(_make_client_with_schemas())
        with pytest.raises(ToolError, match="Kind 'BadKind' not found"):
            await explore(kind="BadKind", ctx=ctx)
