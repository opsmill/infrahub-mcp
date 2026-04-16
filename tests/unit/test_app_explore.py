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

_FAKE_NODES = [
    {"name": "device-1", "status": "active", "platform": "Juniper"},
    {"name": "device-2", "status": "active", "platform": "Cisco"},
    {"name": "device-3", "status": "decommissioned", "platform": "Juniper"},
]

_FAKE_COLUMNS = ["name", "status", "platform"]


def _patch_all():
    """Patch _validate_kind, _fetch_schema_detail, and _fetch_nodes_for_kind."""

    def decorator(func):
        @patch("infrahub_app.explore._fetch_nodes_for_kind", return_value=(_FAKE_NODES, _FAKE_COLUMNS))
        @patch("infrahub_app.explore._fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
        @patch("infrahub_app.explore._validate_kind", return_value="InfraDevice")
        async def wrapper(self, mock_validate, mock_schema, mock_nodes):
            return await func(self, mock_validate, mock_schema, mock_nodes)

        return wrapper

    return decorator


class TestFetchExploreData:
    @_patch_all()
    async def test_returns_expected_keys(
        self, mock_validate: MagicMock, mock_schema: MagicMock, mock_nodes: MagicMock,
    ) -> None:
        ctx = _make_ctx()
        result = await fetch_explore_data(kind="InfraDevice", ctx=ctx)
        assert "nodes" in result
        assert "columns" in result
        assert "schema" in result
        assert "distributions" in result

    @_patch_all()
    async def test_distributions_computed_for_chartable_fields(
        self, mock_validate: MagicMock, mock_schema: MagicMock, mock_nodes: MagicMock,
    ) -> None:
        ctx = _make_ctx()
        result = await fetch_explore_data(kind="InfraDevice", ctx=ctx)
        dist_fields = {d["field"] for d in result["distributions"]}
        # Relationship labels include peer kind: "platform (InfraPlatform)"
        assert "status" in dist_fields
        assert "platform (InfraPlatform)" in dist_fields


class TestExploreUI:
    @_patch_all()
    async def test_returns_prefab_app(
        self, mock_validate: MagicMock, mock_schema: MagicMock, mock_nodes: MagicMock,
    ) -> None:
        ctx = _make_ctx()
        result = await explore(kind="InfraDevice", ctx=ctx)
        assert isinstance(result, PrefabApp)

    @_patch_all()
    async def test_has_correct_title(
        self, mock_validate: MagicMock, mock_schema: MagicMock, mock_nodes: MagicMock,
    ) -> None:
        ctx = _make_ctx()
        result = await explore(kind="InfraDevice", ctx=ctx)
        assert result.title == "Explore: InfraDevice"  # type: ignore[attr-defined]

    @_patch_all()
    async def test_state_has_node_count(
        self, mock_validate: MagicMock, mock_schema: MagicMock, mock_nodes: MagicMock,
    ) -> None:
        ctx = _make_ctx()
        result = await explore(kind="InfraDevice", ctx=ctx)
        assert result.state["node_count"] == 3  # type: ignore[attr-defined]
        assert result.state["attr_count"] == 2  # type: ignore[attr-defined]
        assert result.state["rel_count"] == 1  # type: ignore[attr-defined]

    @_patch_all()
    async def test_custom_panels_used(
        self, mock_validate: MagicMock, mock_schema: MagicMock, mock_nodes: MagicMock,
    ) -> None:
        ctx = _make_ctx()
        custom_panels = [{"type": "bar", "field": "status", "options": {"horizontal": True}}]
        result = await explore(kind="InfraDevice", ctx=ctx, panels=custom_panels)
        assert isinstance(result, PrefabApp)
        assert "pie_panels" in result.state  # type: ignore[attr-defined]
        assert "bar_panels" in result.state  # type: ignore[attr-defined]

    @patch("infrahub_app.explore._validate_kind", side_effect=ToolError("Kind 'BadKind' not found."))
    async def test_raises_on_invalid_kind(self, mock_validate: MagicMock) -> None:
        ctx = _make_ctx()
        with pytest.raises(ToolError, match="Kind 'BadKind' not found"):
            await explore(kind="BadKind", ctx=ctx)
