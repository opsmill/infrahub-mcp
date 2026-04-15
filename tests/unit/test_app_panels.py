"""Tests for the panel engine (panels.py)."""

from __future__ import annotations

from typing import Any

import pytest
from prefab_ui.components.charts import BarChart, PieChart

from infrahub_app.panels import PanelConfig, auto_detect_panels, build_panel, compute_distribution


class TestPanelConfig:
    def test_creates_with_defaults(self) -> None:
        panel = PanelConfig(type="pie", field="status")
        assert panel.type == "pie"
        assert panel.field == "status"
        assert panel.options == {}

    def test_creates_with_options(self) -> None:
        panel = PanelConfig(type="bar", field="role", options={"horizontal": True, "limit": 5})
        assert panel.options["horizontal"] is True
        assert panel.options["limit"] == 5

    def test_creates_from_dict(self) -> None:
        raw = {"type": "bar", "field": "status", "options": {"stacked": True}}
        panel = PanelConfig.from_dict(raw)
        assert panel.type == "bar"
        assert panel.field == "status"
        assert panel.options["stacked"] is True

    def test_from_dict_defaults_missing_options(self) -> None:
        raw = {"type": "pie", "field": "role"}
        panel = PanelConfig.from_dict(raw)
        assert panel.options == {}


class TestComputeDistribution:
    def test_counts_values(self) -> None:
        nodes = [
            {"status": "active"},
            {"status": "active"},
            {"status": "decommissioned"},
        ]
        result = compute_distribution(nodes, "status")
        assert result == [
            {"name": "active", "count": 2},
            {"name": "decommissioned", "count": 1},
        ]

    def test_respects_limit(self) -> None:
        nodes = [{"x": str(i)} for i in range(50)]
        result = compute_distribution(nodes, "x", limit=5)
        assert len(result) == 5

    def test_skips_none_values(self) -> None:
        nodes = [{"status": "active"}, {"status": None}, {}]
        result = compute_distribution(nodes, "status")
        assert len(result) == 1
        assert result[0]["name"] == "active"

    def test_empty_nodes(self) -> None:
        result = compute_distribution([], "status")
        assert result == []

    def test_handles_list_values_for_many_relationships(self) -> None:
        nodes = [
            {"tags": ["web", "prod"]},
            {"tags": ["web", "staging"]},
            {"tags": ["db"]},
        ]
        result = compute_distribution(nodes, "tags")
        names = {r["name"] for r in result}
        assert "web" in names
        assert "prod" in names
        counts = {r["name"]: r["count"] for r in result}
        assert counts["web"] == 2


_FAKE_SCHEMA: dict[str, Any] = {
    "kind": "InfraDevice",
    "attributes": [
        {"name": "name", "kind": "Text", "optional": False},
        {"name": "status", "kind": "Dropdown", "optional": False},
        {"name": "enabled", "kind": "Boolean", "optional": False},
        {"name": "mtu", "kind": "Number", "optional": True},
        {"name": "description", "kind": "Text", "optional": True},
    ],
    "relationships": [
        {"name": "platform", "peer": "InfraPlatform", "cardinality": "one"},
        {"name": "tags", "peer": "BuiltinTag", "cardinality": "many"},
    ],
}


class TestAutoDetectPanels:
    def test_dropdown_becomes_pie(self) -> None:
        panels = auto_detect_panels(_FAKE_SCHEMA)
        status_panels = [p for p in panels if p.field == "status"]
        assert len(status_panels) == 1
        assert status_panels[0].type == "pie"

    def test_boolean_becomes_pie(self) -> None:
        panels = auto_detect_panels(_FAKE_SCHEMA)
        enabled_panels = [p for p in panels if p.field == "enabled"]
        assert len(enabled_panels) == 1
        assert enabled_panels[0].type == "pie"

    def test_number_becomes_bar(self) -> None:
        panels = auto_detect_panels(_FAKE_SCHEMA)
        mtu_panels = [p for p in panels if p.field == "mtu"]
        assert len(mtu_panels) == 1
        assert mtu_panels[0].type == "bar"

    def test_text_fields_skipped(self) -> None:
        panels = auto_detect_panels(_FAKE_SCHEMA)
        field_names = {p.field for p in panels}
        assert "name" not in field_names
        assert "description" not in field_names

    def test_one_cardinality_rel_becomes_pie(self) -> None:
        panels = auto_detect_panels(_FAKE_SCHEMA)
        platform_panels = [p for p in panels if p.field == "platform"]
        assert len(platform_panels) == 1
        assert platform_panels[0].type == "pie"

    def test_many_cardinality_rel_becomes_bar(self) -> None:
        panels = auto_detect_panels(_FAKE_SCHEMA)
        tags_panels = [p for p in panels if p.field == "tags"]
        assert len(tags_panels) == 1
        assert tags_panels[0].type == "bar"


class TestBuildPanel:
    def test_pie_panel(self) -> None:
        panel = PanelConfig(type="pie", field="status")
        data = [{"name": "active", "count": 5}, {"name": "down", "count": 2}]
        component = build_panel(panel, data)
        assert isinstance(component, PieChart)

    def test_bar_panel(self) -> None:
        panel = PanelConfig(type="bar", field="mtu")
        data = [{"name": "1500", "count": 10}, {"name": "9000", "count": 3}]
        component = build_panel(panel, data)
        assert isinstance(component, BarChart)

    def test_bar_horizontal_option(self) -> None:
        panel = PanelConfig(type="bar", field="role", options={"horizontal": True})
        data = [{"name": "spine", "count": 4}]
        component = build_panel(panel, data)
        assert isinstance(component, BarChart)
        assert component.horizontal is True  # type: ignore[attr-defined]

    def test_bar_stacked_option(self) -> None:
        panel = PanelConfig(type="bar", field="x", options={"stacked": True})
        data = [{"name": "a", "count": 1}]
        component = build_panel(panel, data)
        assert isinstance(component, BarChart)
        assert component.stacked is True  # type: ignore[attr-defined]

    def test_unknown_type_raises(self) -> None:
        panel = PanelConfig(type="unknown_chart", field="x")
        with pytest.raises(ValueError, match="Unsupported panel type"):
            build_panel(panel, [])
