# Infrahub App (FastMCPApp) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the baked-in `reports/` module with a generic FastMCPApp that provides schema-agnostic `explore` and `overview` visualization tools for any Infrahub instance.

**Architecture:** Three-layer Hitchhiker's Guide pattern. The existing MCP Server stays unchanged (data/action API). A new `FastMCPApp("Infrahub")` provides generic visualization tools that fetch data via SDK client and render Prefab components. A standalone example app (out of scope for this plan) will later demonstrate domain-specific dashboards built on top.

**Tech Stack:** Python 3.13+, FastMCP (FastMCPApp), Prefab UI (PrefabApp, charts, Rx, ForEach, CallTool/SetState), Infrahub SDK

---

## File Structure

```
src/infrahub_app/              # NEW package (separate from infrahub_mcp)
├── __init__.py                # Exports `app` for mounting
├── app.py                     # FastMCPApp("Infrahub") instance + context helpers
├── panels.py                  # PanelConfig dataclass, auto_detect_panels(), build_panel(), compute_distribution()
├── explore.py                 # @app.ui() explore + @app.tool() fetch_explore_data
└── overview.py                # @app.ui() overview + @app.tool() fetch_overview_data

tests/unit/
├── test_app_panels.py         # NEW — unit tests for panels.py
├── test_app_explore.py        # NEW — unit tests for explore.py
└── test_app_overview.py       # NEW — unit tests for overview.py

src/infrahub_mcp/reports/      # DELETE entire directory
tests/unit/test_report_*.py    # DELETE all four files
```

**Why this split:** `panels.py` is pure logic (no async, no SDK) — easy to test in isolation. `explore.py` and `overview.py` each own their UI entry point + backend tool. `app.py` is the glue: the FastMCPApp instance and shared context helpers.

---

### Task 1: Delete the old `reports/` module and all its tests

**Files:**
- Delete: `src/infrahub_mcp/reports/__init__.py`
- Delete: `src/infrahub_mcp/reports/reports.py`
- Delete: `src/infrahub_mcp/reports/fetchers.py`
- Delete: `src/infrahub_mcp/reports/charts.py`
- Delete: `src/infrahub_mcp/reports/store.py`
- Delete: `tests/unit/test_report_reports.py`
- Delete: `tests/unit/test_report_fetchers.py`
- Delete: `tests/unit/test_report_charts.py`
- Delete: `tests/unit/test_report_store.py`
- Modify: `src/infrahub_mcp/server.py:21,229` — remove reports import and mount
- Modify: `pyproject.toml:45-50` — remove mypy overrides for `infrahub_mcp.reports.*`

- [ ] **Step 1: Remove reports mount from server.py**

In `src/infrahub_mcp/server.py`, remove the import on line 22:

```python
from infrahub_mcp.reports import mcp as reports_mcp
```

And remove the mount on line 229:

```python
mcp.mount(reports_mcp)
```

And remove the comment on line 228:

```python
# Analytics reports — interactive visual reports (PrefabApp)
```

- [ ] **Step 2: Remove mypy overrides from pyproject.toml**

In `pyproject.toml`, remove these two override blocks (lines 45-50):

```toml
[[tool.mypy.overrides]]
module = "infrahub_mcp.reports.charts"
disable_error_code = ["call-arg", "arg-type"]

[[tool.mypy.overrides]]
module = "infrahub_mcp.reports.reports"
disable_error_code = ["call-arg", "call-overload"]
```

- [ ] **Step 3: Delete all reports source files**

```bash
rm -rf src/infrahub_mcp/reports/
```

- [ ] **Step 4: Delete all reports test files**

```bash
rm tests/unit/test_report_reports.py tests/unit/test_report_fetchers.py tests/unit/test_report_charts.py tests/unit/test_report_store.py
```

- [ ] **Step 5: Run tests to verify clean removal**

Run: `uv run pytest tests/ -v`
Expected: All remaining tests PASS. No import errors referencing `infrahub_mcp.reports`.

- [ ] **Step 6: Run linters**

Run: `uv run pre-commit run --all-files`
Expected: PASS (no references to deleted modules).

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor: delete reports/ module, replaced by infrahub_app in next commits"
```

---

### Task 2: Create the `infrahub_app` package skeleton and register it

**Files:**
- Create: `src/infrahub_app/__init__.py`
- Create: `src/infrahub_app/app.py`
- Modify: `pyproject.toml` — add hatchling package discovery for `infrahub_app`
- Modify: `src/infrahub_mcp/server.py` — mount the new app

- [ ] **Step 1: Write the failing test — app can be imported and is a FastMCPApp**

Create `tests/unit/test_app_explore.py` with a minimal import test:

```python
"""Tests for the infrahub_app package skeleton."""

from __future__ import annotations

from fastmcp.apps import FastMCPApp


def test_app_is_fastmcp_app() -> None:
    from infrahub_app import app

    assert isinstance(app, FastMCPApp)
    assert app.name == "Infrahub"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_app_explore.py::test_app_is_fastmcp_app -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'infrahub_app'`

- [ ] **Step 3: Add hatchling package discovery to pyproject.toml**

Hatchling auto-discovers packages under `src/` by default. Since there's no explicit `[tool.hatch.build.targets.wheel]` config, adding `src/infrahub_app/` should be auto-discovered. But to be explicit, add after the `[build-system]` block:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/infrahub_mcp", "src/infrahub_app"]
```

- [ ] **Step 4: Create `src/infrahub_app/__init__.py`**

```python
"""Infrahub FastMCPApp — generic, schema-agnostic visualization tools."""

from infrahub_app.app import app

__all__ = ["app"]
```

- [ ] **Step 5: Create `src/infrahub_app/app.py`**

```python
"""FastMCPApp instance and shared context helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp import Context
from fastmcp.apps import FastMCPApp

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient

    from infrahub_mcp.utils import AppContext

app = FastMCPApp("Infrahub")


def get_app_ctx(ctx: Context) -> AppContext:
    """Extract the AppContext from the MCP request context."""
    return ctx.request_context.lifespan_context  # type: ignore[union-attr,return-value]


def get_client(ctx: Context) -> InfrahubClient:
    """Extract the Infrahub SDK client from the MCP request context."""
    return get_app_ctx(ctx).client
```

- [ ] **Step 6: Mount the app in server.py**

In `src/infrahub_mcp/server.py`, add the import (after the existing tool imports):

```python
from infrahub_app import app as infrahub_app
```

And at the bottom of the file (where the old `reports_mcp` mount was), add:

```python
# Infrahub App — generic visualization tools (FastMCPApp)
mcp.mount(infrahub_app)
```

- [ ] **Step 7: Reinstall and run test**

Run: `uv sync && uv run pytest tests/unit/test_app_explore.py::test_app_is_fastmcp_app -v`
Expected: PASS

- [ ] **Step 8: Run full test suite and linters**

Run: `uv run pytest tests/ -v && uv run pre-commit run --all-files`
Expected: All PASS.

- [ ] **Step 9: Commit**

```bash
git add src/infrahub_app/__init__.py src/infrahub_app/app.py src/infrahub_mcp/server.py pyproject.toml tests/unit/test_app_explore.py
git commit -m "feat: add infrahub_app package skeleton with FastMCPApp"
```

---

### Task 3: Implement `panels.py` — PanelConfig, compute_distribution, auto_detect_panels, build_panel

This is the core engine. Pure logic, no async, no SDK dependency.

**Files:**
- Create: `src/infrahub_app/panels.py`
- Create: `tests/unit/test_app_panels.py`

- [ ] **Step 1: Write test for PanelConfig dataclass**

Create `tests/unit/test_app_panels.py`:

```python
"""Tests for the panel engine (panels.py)."""

from __future__ import annotations

from typing import Any

import pytest


class TestPanelConfig:
    def test_creates_with_defaults(self) -> None:
        from infrahub_app.panels import PanelConfig

        panel = PanelConfig(type="pie", field="status")
        assert panel.type == "pie"
        assert panel.field == "status"
        assert panel.options == {}

    def test_creates_with_options(self) -> None:
        from infrahub_app.panels import PanelConfig

        panel = PanelConfig(type="bar", field="role", options={"horizontal": True, "limit": 5})
        assert panel.options["horizontal"] is True
        assert panel.options["limit"] == 5

    def test_creates_from_dict(self) -> None:
        from infrahub_app.panels import PanelConfig

        raw = {"type": "bar", "field": "status", "options": {"stacked": True}}
        panel = PanelConfig.from_dict(raw)
        assert panel.type == "bar"
        assert panel.field == "status"
        assert panel.options["stacked"] is True

    def test_from_dict_defaults_missing_options(self) -> None:
        from infrahub_app.panels import PanelConfig

        raw = {"type": "pie", "field": "role"}
        panel = PanelConfig.from_dict(raw)
        assert panel.options == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_app_panels.py::TestPanelConfig -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Implement PanelConfig**

Create `src/infrahub_app/panels.py`:

```python
"""Panel engine — config parsing, auto-detection, chart building.

This module is pure logic with no async or SDK dependencies.
It converts panel configurations into Prefab UI chart components.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter
from typing import Any

from prefab_ui.components import DataTable, DataTableColumn, Grid, Metric
from prefab_ui.components.charts import AreaChart, BarChart, ChartSeries, LineChart, PieChart
from prefab_ui.components.mermaid import Mermaid


@dataclass
class PanelConfig:
    """Configuration for a single chart panel."""

    type: str  # "pie", "bar", "line", "area", "metric", "table"
    field: str  # attribute or relationship name
    options: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> PanelConfig:
        """Create a PanelConfig from a raw dict (user input)."""
        return cls(
            type=raw["type"],
            field=raw["field"],
            options=raw.get("options", {}),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_app_panels.py::TestPanelConfig -v`
Expected: PASS

- [ ] **Step 5: Write test for compute_distribution**

Append to `tests/unit/test_app_panels.py`:

```python
class TestComputeDistribution:
    def test_counts_values(self) -> None:
        from infrahub_app.panels import compute_distribution

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
        from infrahub_app.panels import compute_distribution

        nodes = [{"x": str(i)} for i in range(50)]
        result = compute_distribution(nodes, "x", limit=5)
        assert len(result) == 5

    def test_skips_none_values(self) -> None:
        from infrahub_app.panels import compute_distribution

        nodes = [{"status": "active"}, {"status": None}, {}]
        result = compute_distribution(nodes, "status")
        assert len(result) == 1
        assert result[0]["name"] == "active"

    def test_empty_nodes(self) -> None:
        from infrahub_app.panels import compute_distribution

        result = compute_distribution([], "status")
        assert result == []

    def test_handles_list_values_for_many_relationships(self) -> None:
        from infrahub_app.panels import compute_distribution

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
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_app_panels.py::TestComputeDistribution -v`
Expected: FAIL with `ImportError`

- [ ] **Step 7: Implement compute_distribution**

Add to `src/infrahub_app/panels.py`:

```python
def compute_distribution(
    nodes: list[dict[str, Any]], field: str, limit: int = 20
) -> list[dict[str, Any]]:
    """Count occurrences of each value for a field. Return sorted top-N.

    Handles both scalar values and list values (many-cardinality relationships).
    Skips None values and missing keys.
    """
    if not nodes:
        return []

    counter: Counter[str] = Counter()
    for node in nodes:
        raw = node.get(field)
        if raw is None:
            continue
        if isinstance(raw, list):
            for item in raw:
                if item is not None:
                    counter[str(item)] += 1
        else:
            counter[str(raw)] += 1

    return [{"name": name, "count": count} for name, count in counter.most_common(limit)]
```

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_app_panels.py::TestComputeDistribution -v`
Expected: PASS

- [ ] **Step 9: Write test for auto_detect_panels**

Append to `tests/unit/test_app_panels.py`:

```python
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
        from infrahub_app.panels import auto_detect_panels

        panels = auto_detect_panels(_FAKE_SCHEMA)
        status_panels = [p for p in panels if p.field == "status"]
        assert len(status_panels) == 1
        assert status_panels[0].type == "pie"

    def test_boolean_becomes_pie(self) -> None:
        from infrahub_app.panels import auto_detect_panels

        panels = auto_detect_panels(_FAKE_SCHEMA)
        enabled_panels = [p for p in panels if p.field == "enabled"]
        assert len(enabled_panels) == 1
        assert enabled_panels[0].type == "pie"

    def test_number_becomes_bar(self) -> None:
        from infrahub_app.panels import auto_detect_panels

        panels = auto_detect_panels(_FAKE_SCHEMA)
        mtu_panels = [p for p in panels if p.field == "mtu"]
        assert len(mtu_panels) == 1
        assert mtu_panels[0].type == "bar"

    def test_text_fields_skipped(self) -> None:
        from infrahub_app.panels import auto_detect_panels

        panels = auto_detect_panels(_FAKE_SCHEMA)
        field_names = {p.field for p in panels}
        assert "name" not in field_names
        assert "description" not in field_names

    def test_one_cardinality_rel_becomes_pie(self) -> None:
        from infrahub_app.panels import auto_detect_panels

        panels = auto_detect_panels(_FAKE_SCHEMA)
        platform_panels = [p for p in panels if p.field == "platform"]
        assert len(platform_panels) == 1
        assert platform_panels[0].type == "pie"

    def test_many_cardinality_rel_becomes_bar(self) -> None:
        from infrahub_app.panels import auto_detect_panels

        panels = auto_detect_panels(_FAKE_SCHEMA)
        tags_panels = [p for p in panels if p.field == "tags"]
        assert len(tags_panels) == 1
        assert tags_panels[0].type == "bar"
```

- [ ] **Step 10: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_app_panels.py::TestAutoDetectPanels -v`
Expected: FAIL

- [ ] **Step 11: Implement auto_detect_panels**

Add to `src/infrahub_app/panels.py`:

```python
# Attribute kinds that map to specific chart types
_ATTR_KIND_TO_CHART: dict[str, str] = {
    "Dropdown": "pie",
    "Boolean": "pie",
    "Number": "bar",
    "Integer": "bar",
}


def auto_detect_panels(schema: dict[str, Any]) -> list[PanelConfig]:
    """Introspect a schema and return sensible panel configs.

    Rules:
    - Dropdown/Boolean attributes -> pie chart
    - Number/Integer attributes -> bar chart
    - Text and other attributes -> skipped
    - one-cardinality relationships -> pie chart (peer distribution)
    - many-cardinality relationships -> bar chart (count distribution)
    """
    panels: list[PanelConfig] = []

    for attr in schema.get("attributes", []):
        chart_type = _ATTR_KIND_TO_CHART.get(attr["kind"])
        if chart_type:
            panels.append(PanelConfig(type=chart_type, field=attr["name"]))

    for rel in schema.get("relationships", []):
        if rel.get("cardinality") == "many":
            panels.append(PanelConfig(type="bar", field=rel["name"]))
        else:
            panels.append(PanelConfig(type="pie", field=rel["name"]))

    return panels
```

- [ ] **Step 12: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_app_panels.py::TestAutoDetectPanels -v`
Expected: PASS

- [ ] **Step 13: Write test for build_panel**

Append to `tests/unit/test_app_panels.py`:

```python
from prefab_ui.components.charts import BarChart, PieChart


class TestBuildPanel:
    def test_pie_panel(self) -> None:
        from infrahub_app.panels import PanelConfig, build_panel

        panel = PanelConfig(type="pie", field="status")
        data = [{"name": "active", "count": 5}, {"name": "down", "count": 2}]
        component = build_panel(panel, data)
        assert isinstance(component, PieChart)

    def test_bar_panel(self) -> None:
        from infrahub_app.panels import PanelConfig, build_panel

        panel = PanelConfig(type="bar", field="mtu")
        data = [{"name": "1500", "count": 10}, {"name": "9000", "count": 3}]
        component = build_panel(panel, data)
        assert isinstance(component, BarChart)

    def test_bar_horizontal_option(self) -> None:
        from infrahub_app.panels import PanelConfig, build_panel

        panel = PanelConfig(type="bar", field="role", options={"horizontal": True})
        data = [{"name": "spine", "count": 4}]
        component = build_panel(panel, data)
        assert isinstance(component, BarChart)
        assert component.horizontal is True  # type: ignore[attr-defined]

    def test_bar_stacked_option(self) -> None:
        from infrahub_app.panels import PanelConfig, build_panel

        panel = PanelConfig(type="bar", field="x", options={"stacked": True})
        data = [{"name": "a", "count": 1}]
        component = build_panel(panel, data)
        assert isinstance(component, BarChart)
        assert component.stacked is True  # type: ignore[attr-defined]

    def test_unknown_type_raises(self) -> None:
        from infrahub_app.panels import PanelConfig, build_panel

        panel = PanelConfig(type="unknown_chart", field="x")
        with pytest.raises(ValueError, match="Unsupported panel type"):
            build_panel(panel, [])
```

- [ ] **Step 14: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_app_panels.py::TestBuildPanel -v`
Expected: FAIL

- [ ] **Step 15: Implement build_panel**

Add to `src/infrahub_app/panels.py`:

```python
from prefab_ui.components.base import Component


def build_panel(panel: PanelConfig, data: list[dict[str, Any]]) -> Component:
    """Build a Prefab chart component from a panel config and distribution data.

    Args:
        panel: Panel configuration specifying chart type and options.
        data: Distribution data — list of dicts with "name" and "count" keys.

    Returns:
        A Prefab Component (PieChart, BarChart, etc.).

    Raises:
        ValueError: If panel.type is not supported.
    """
    opts = panel.options

    if panel.type == "pie":
        return PieChart(data=data, data_key="count", name_key="name")

    if panel.type == "bar":
        series_keys = opts.get("series", ["count"])
        series = [ChartSeries(data_key=key) for key in series_keys]
        return BarChart(
            data=data,
            x_axis="name",
            series=series,
            horizontal=opts.get("horizontal", False),
            stacked=opts.get("stacked", False),
        )

    if panel.type == "line":
        series_keys = opts.get("series", ["count"])
        series = [ChartSeries(data_key=key) for key in series_keys]
        return LineChart(data=data, x_axis="name", series=series)

    if panel.type == "area":
        series_keys = opts.get("series", ["count"])
        series = [ChartSeries(data_key=key) for key in series_keys]
        return AreaChart(
            data=data,
            x_axis="name",
            series=series,
            stacked=opts.get("stacked", False),
        )

    msg = f"Unsupported panel type: {panel.type!r}"
    raise ValueError(msg)
```

- [ ] **Step 16: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_app_panels.py::TestBuildPanel -v`
Expected: PASS

- [ ] **Step 17: Run full panels test suite and linters**

Run: `uv run pytest tests/unit/test_app_panels.py -v && uv run pre-commit run --all-files`
Expected: All PASS.

- [ ] **Step 18: Commit**

```bash
git add src/infrahub_app/panels.py tests/unit/test_app_panels.py
git commit -m "feat: add panel engine with auto-detect, distribution, and chart building"
```

---

### Task 4: Implement `explore.py` — data fetching, UI entry point, backend tool

**Files:**
- Create: `src/infrahub_app/explore.py`
- Modify: `tests/unit/test_app_explore.py` — add explore tests

**Context:** This module provides `@app.ui() explore` (the visual entry point) and `@app.tool() fetch_explore_data` (the backend tool for re-fetching on filter change). It uses `panels.py` for chart generation. Data fetching replicates what `reports/fetchers.py` did but lives directly in this module — simpler, no separate fetchers package.

- [ ] **Step 1: Write test for fetch_explore_data backend tool**

Replace the contents of `tests/unit/test_app_explore.py` (keeping the skeleton test from Task 2):

```python
"""Tests for the explore tool (explore.py)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Context
from fastmcp.apps import FastMCPApp
from prefab_ui.app import PrefabApp

from infrahub_app import app


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


class TestFetchExploreData:
    @patch("infrahub_app.explore._fetch_nodes_for_kind", return_value=(_FAKE_NODES, _FAKE_COLUMNS))
    @patch("infrahub_app.explore._fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    async def test_returns_expected_keys(
        self, mock_schema: MagicMock, mock_nodes: MagicMock,
    ) -> None:
        from infrahub_app.explore import fetch_explore_data

        ctx = _make_ctx()
        result = await fetch_explore_data(kind="InfraDevice", ctx=ctx)
        assert "nodes" in result
        assert "columns" in result
        assert "schema" in result
        assert "distributions" in result

    @patch("infrahub_app.explore._fetch_nodes_for_kind", return_value=(_FAKE_NODES, _FAKE_COLUMNS))
    @patch("infrahub_app.explore._fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    async def test_distributions_computed_for_chartable_fields(
        self, mock_schema: MagicMock, mock_nodes: MagicMock,
    ) -> None:
        from infrahub_app.explore import fetch_explore_data

        ctx = _make_ctx()
        result = await fetch_explore_data(kind="InfraDevice", ctx=ctx)
        dist_fields = {d["field"] for d in result["distributions"]}
        assert "status" in dist_fields  # Dropdown -> chartable
        assert "platform" in dist_fields  # Relationship -> chartable


class TestExploreUI:
    @patch("infrahub_app.explore._fetch_nodes_for_kind", return_value=(_FAKE_NODES, _FAKE_COLUMNS))
    @patch("infrahub_app.explore._fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    async def test_returns_prefab_app(
        self, mock_schema: MagicMock, mock_nodes: MagicMock,
    ) -> None:
        from infrahub_app.explore import explore

        ctx = _make_ctx()
        result = await explore(kind="InfraDevice", ctx=ctx)
        assert isinstance(result, PrefabApp)

    @patch("infrahub_app.explore._fetch_nodes_for_kind", return_value=(_FAKE_NODES, _FAKE_COLUMNS))
    @patch("infrahub_app.explore._fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    async def test_has_correct_title(
        self, mock_schema: MagicMock, mock_nodes: MagicMock,
    ) -> None:
        from infrahub_app.explore import explore

        ctx = _make_ctx()
        result = await explore(kind="InfraDevice", ctx=ctx)
        assert result.title == "Explore: InfraDevice"  # type: ignore[attr-defined]

    @patch("infrahub_app.explore._fetch_nodes_for_kind", return_value=(_FAKE_NODES, _FAKE_COLUMNS))
    @patch("infrahub_app.explore._fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    async def test_state_has_node_count(
        self, mock_schema: MagicMock, mock_nodes: MagicMock,
    ) -> None:
        from infrahub_app.explore import explore

        ctx = _make_ctx()
        result = await explore(kind="InfraDevice", ctx=ctx)
        assert result.state["node_count"] == 3  # type: ignore[attr-defined]
        assert result.state["attr_count"] == 2  # type: ignore[attr-defined]
        assert result.state["rel_count"] == 1  # type: ignore[attr-defined]

    @patch("infrahub_app.explore._fetch_nodes_for_kind", return_value=(_FAKE_NODES, _FAKE_COLUMNS))
    @patch("infrahub_app.explore._fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    async def test_custom_panels_used(
        self, mock_schema: MagicMock, mock_nodes: MagicMock,
    ) -> None:
        from infrahub_app.explore import explore

        ctx = _make_ctx()
        custom_panels = [{"type": "bar", "field": "status", "options": {"horizontal": True}}]
        result = await explore(kind="InfraDevice", ctx=ctx, panels=custom_panels)
        assert isinstance(result, PrefabApp)
        # With custom panels, the state should still have panels_data
        assert "panels_data" in result.state  # type: ignore[attr-defined]

    @patch("infrahub_app.explore._fetch_schema_detail", side_effect=Exception("Schema fetch failed"))
    async def test_raises_on_error(self, mock_schema: MagicMock) -> None:
        from infrahub_app.explore import explore

        ctx = _make_ctx()
        with pytest.raises(Exception, match="Schema fetch failed"):
            await explore(kind="BadKind", ctx=ctx)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_app_explore.py -v`
Expected: FAIL — `ImportError` for `infrahub_app.explore`

- [ ] **Step 3: Implement explore.py**

Create `src/infrahub_app/explore.py`:

```python
"""Explore tool — visualize nodes of a single kind with auto-detected or custom charts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastmcp import Context
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    H3,
    Column,
    DataTable,
    DataTableColumn,
    Grid,
    Metric,
    P,
    Tab,
    Tabs,
)
from prefab_ui.components.control_flow.foreach import ForEach
from prefab_ui.rx import Rx

from infrahub_app.app import app, get_client
from infrahub_app.panels import PanelConfig, auto_detect_panels, build_panel, compute_distribution

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient

from infrahub_mcp.utils import convert_node_to_dict


async def _fetch_schema_detail(
    client: InfrahubClient, kind: str, branch: str | None = None,
) -> dict[str, Any]:
    """Fetch detailed schema for a kind."""
    schema = await client.schema.get(kind=kind, branch=branch)
    return {
        "kind": schema.kind,
        "attributes": [
            {"name": attr.name, "kind": attr.kind, "optional": attr.optional}
            for attr in schema.attributes
        ],
        "relationships": [
            {"name": rel.name, "peer": rel.peer, "cardinality": rel.cardinality}
            for rel in schema.relationships
        ],
    }


async def _fetch_nodes_for_kind(
    client: InfrahubClient,
    kind: str,
    branch: str | None = None,
    filters: dict[str, Any] | None = None,
    limit: int = 200,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch nodes of a kind, return (rows, column_names)."""
    schema = await client.schema.get(kind=kind, branch=branch)
    column_names: list[str] = [attr.name for attr in schema.attributes] + [
        rel.name for rel in schema.relationships
    ]
    nodes = await client.all(kind=kind, branch=branch, limit=limit, **(filters or {}))
    rows: list[dict[str, Any]] = []
    for node in nodes:
        row = await convert_node_to_dict(obj=node, branch=branch)
        rows.append(row)
    return rows, column_names


def _compute_distributions(
    nodes: list[dict[str, Any]],
    panels: list[PanelConfig],
) -> list[dict[str, Any]]:
    """Compute distribution data for each panel's field."""
    result: list[dict[str, Any]] = []
    for panel in panels:
        limit = panel.options.get("limit", 20)
        dist = compute_distribution(nodes, panel.field, limit=limit)
        if dist:
            result.append({"field": panel.field, "type": panel.type, "data": dist})
    return result


@app.tool()
async def fetch_explore_data(
    kind: str,
    ctx: Context,
    branch: str | None = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch data for the explore view. Called on filter changes via CallTool."""
    client = get_client(ctx)
    schema = await _fetch_schema_detail(client, kind, branch)
    nodes, columns = await _fetch_nodes_for_kind(client, kind, branch, filters)
    panels = auto_detect_panels(schema)
    distributions = _compute_distributions(nodes, panels)
    return {
        "nodes": nodes,
        "columns": columns,
        "schema": schema,
        "distributions": distributions,
    }


@app.ui()
async def explore(
    kind: str,
    ctx: Context,
    branch: str | None = None,
    filters: dict[str, Any] | None = None,
    panels: list[dict[str, Any]] | None = None,
) -> PrefabApp:
    """Visualize nodes of a single kind with auto-detected or custom charts."""
    client = get_client(ctx)

    schema = await _fetch_schema_detail(client, kind, branch)
    nodes, columns = await _fetch_nodes_for_kind(client, kind, branch, filters)

    # Resolve panels: use custom if provided, otherwise auto-detect
    if panels:
        panel_configs = [PanelConfig.from_dict(p) for p in panels]
    else:
        panel_configs = auto_detect_panels(schema)

    distributions = _compute_distributions(nodes, panel_configs)
    panels_data = [
        {"field": d["field"], "type": d["type"], "data": d["data"]}
        for d in distributions
    ]

    table_columns = [{"key": c, "header": c.replace("_", " ").title()} for c in columns]

    with PrefabApp(
        title=f"Explore: {kind}",
        state={
            "node_count": len(nodes),
            "attr_count": len(schema["attributes"]),
            "rel_count": len(schema["relationships"]),
            "panels_data": panels_data,
            "table_rows": nodes,
            "table_columns": table_columns,
        },
    ) as prefab_app:
        with Tabs(value="overview"):
            with Tab("Overview"):
                with Column():
                    with Grid(columns=3):
                        Metric(label="Nodes", value=Rx("node_count"))
                        Metric(label="Attributes", value=Rx("attr_count"))
                        Metric(label="Relationships", value=Rx("rel_count"))
                    H3(content="Charts")
                    with ForEach(Rx("panels_data")) as (_idx, panel_item):
                        P(content=panel_item.field)
                        # Build charts inline — ForEach items are reactive,
                        # so we use PieChart/BarChart with the loop item's data
                        # For simplicity in the ForEach context, we render
                        # all distributions as PieCharts (the most common auto-detect)
                        # A future enhancement can switch on panel_item.type
                        from prefab_ui.components.charts import PieChart

                        PieChart(data=panel_item.data, data_key="count", name_key="name")
            with Tab("Data"):
                with Column():
                    H3(content="Node Data")
                    DataTable(
                        columns=[
                            DataTableColumn(key="name", header="Name", sortable=True),
                            DataTableColumn(key="description", header="Description", sortable=True),
                        ],
                        rows=Rx("table_rows"),  # type: ignore[arg-type]
                        paginated=True,
                        page_size=10,
                    )
    return prefab_app
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_app_explore.py -v`
Expected: PASS

- [ ] **Step 5: Run full suite and linters**

Run: `uv run pytest tests/ -v && uv run pre-commit run --all-files`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add src/infrahub_app/explore.py tests/unit/test_app_explore.py
git commit -m "feat: add explore tool with auto-detect panels and data table"
```

---

### Task 5: Implement `overview.py` — instance-level summary with namespace/coverage/complexity views

**Files:**
- Create: `src/infrahub_app/overview.py`
- Create: `tests/unit/test_app_overview.py`

**Context:** This module provides `@app.ui() overview` and `@app.tool() fetch_overview_data`. It shows instance-wide metrics: namespace distribution, schema coverage (populated vs empty), complexity ranking, and a Mermaid ER diagram.

- [ ] **Step 1: Write tests for overview**

Create `tests/unit/test_app_overview.py`:

```python
"""Tests for the overview tool (overview.py)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Context
from prefab_ui.app import PrefabApp


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
        from infrahub_app.overview import fetch_overview_data

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
        from infrahub_app.overview import fetch_overview_data

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
        from infrahub_app.overview import fetch_overview_data

        ctx = _make_ctx()
        result = await fetch_overview_data(ctx=ctx)
        labels = [c["label"] for c in result["complexity_data"]]
        assert "Account" not in labels  # Core namespace
        assert "Device" in labels


class TestOverviewUI:
    @patch("infrahub_app.overview._fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    @patch("infrahub_app.overview._fetch_node_counts", return_value=_FAKE_COUNTS)
    @patch("infrahub_app.overview._fetch_schema_catalog", return_value=_FAKE_CATALOG)
    async def test_returns_prefab_app(
        self, mock_catalog: MagicMock, mock_counts: MagicMock, mock_detail: MagicMock,
    ) -> None:
        from infrahub_app.overview import overview

        ctx = _make_ctx()
        result = await overview(ctx=ctx)
        assert isinstance(result, PrefabApp)

    @patch("infrahub_app.overview._fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    @patch("infrahub_app.overview._fetch_node_counts", return_value=_FAKE_COUNTS)
    @patch("infrahub_app.overview._fetch_schema_catalog", return_value=_FAKE_CATALOG)
    async def test_has_correct_title(
        self, mock_catalog: MagicMock, mock_counts: MagicMock, mock_detail: MagicMock,
    ) -> None:
        from infrahub_app.overview import overview

        ctx = _make_ctx()
        result = await overview(ctx=ctx)
        assert result.title == "Overview"  # type: ignore[attr-defined]

    @patch("infrahub_app.overview._fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    @patch("infrahub_app.overview._fetch_node_counts", return_value=_FAKE_COUNTS)
    @patch("infrahub_app.overview._fetch_schema_catalog", return_value=_FAKE_CATALOG)
    async def test_state_has_correct_totals(
        self, mock_catalog: MagicMock, mock_counts: MagicMock, mock_detail: MagicMock,
    ) -> None:
        from infrahub_app.overview import overview

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
        from infrahub_app.overview import overview

        ctx = _make_ctx()
        result = await overview(ctx=ctx, filters={"namespace": "Infra"})
        assert isinstance(result, PrefabApp)

    @patch("infrahub_app.overview._fetch_schema_catalog", side_effect=Exception("Connection refused"))
    async def test_raises_on_error(self, mock_catalog: MagicMock) -> None:
        from infrahub_app.overview import overview

        ctx = _make_ctx()
        with pytest.raises(Exception, match="Connection refused"):
            await overview(ctx=ctx)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_app_overview.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement overview.py**

Create `src/infrahub_app/overview.py`:

```python
"""Overview tool — instance-level summary with namespace, coverage, and complexity views."""

from __future__ import annotations

import asyncio
import logging
import operator
from collections import Counter
from typing import TYPE_CHECKING, Any

from fastmcp import Context
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    H3,
    Column,
    DataTable,
    DataTableColumn,
    Grid,
    Metric,
    Tab,
    Tabs,
)
from prefab_ui.components.charts import BarChart, ChartSeries, PieChart
from prefab_ui.components.mermaid import Mermaid
from prefab_ui.rx import Rx

from infrahub_app.app import app, get_client

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient

logger = logging.getLogger(__name__)

_BUILTIN_NAMESPACES = {"Core", "Builtin", "Internal", "Lineage", "Profile"}
_COMPLEXITY_TOP_N = 20
_MERMAID_MAX_KINDS = 30

_CATALOG_TABLE_COLUMNS = [
    DataTableColumn(key="kind", header="Kind", sortable=True),
    DataTableColumn(key="namespace", header="Namespace", sortable=True),
    DataTableColumn(key="label", header="Label", sortable=True),
    DataTableColumn(key="attr_count", header="Attributes", sortable=True),
    DataTableColumn(key="rel_count", header="Relationships", sortable=True),
]


async def _fetch_schema_catalog(
    client: InfrahubClient, branch: str | None = None,
) -> list[dict[str, Any]]:
    """Fetch all concrete kinds from the schema."""
    all_schemas = await client.schema.all(branch=branch)
    return [
        {
            "kind": kind,
            "namespace": schema_obj.namespace,
            "label": schema_obj.label or kind,
            "attr_count": len(schema_obj.attributes),
            "rel_count": len(schema_obj.relationships),
        }
        for kind, schema_obj in all_schemas.items()
    ]


async def _fetch_node_counts(
    client: InfrahubClient,
    kinds: list[str],
    branch: str | None = None,
    concurrency: int = 10,
) -> list[dict[str, Any]]:
    """Fetch node count for each kind concurrently."""
    semaphore = asyncio.Semaphore(concurrency)
    all_schemas = await client.schema.all(branch=branch)
    label_map: dict[str, str] = {k: (v.label or k) for k, v in all_schemas.items()}

    async def _count_one(kind: str) -> dict[str, Any]:
        async with semaphore:
            count = await client.count(kind=kind, branch=branch)
        return {"kind": kind, "label": label_map.get(kind, kind), "count": count}

    results = await asyncio.gather(*[_count_one(kind) for kind in kinds])
    return sorted(results, key=operator.itemgetter("count"), reverse=True)


async def _fetch_schema_detail(
    client: InfrahubClient, kind: str, branch: str | None = None,
) -> dict[str, Any]:
    """Fetch detailed schema for a kind."""
    schema = await client.schema.get(kind=kind, branch=branch)
    return {
        "kind": schema.kind,
        "attributes": [
            {"name": attr.name, "kind": attr.kind, "optional": attr.optional}
            for attr in schema.attributes
        ],
        "relationships": [
            {"name": rel.name, "peer": rel.peer, "cardinality": rel.cardinality}
            for rel in schema.relationships
        ],
    }


def _compute_namespace_data(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group catalog entries by namespace."""
    ns_counter: Counter[str] = Counter()
    for entry in catalog:
        ns_counter[entry["namespace"]] += 1
    return [{"name": ns, "value": count} for ns, count in ns_counter.most_common()]


def _compute_complexity_ranking(
    catalog: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return user-defined kinds sorted by total fields descending."""
    user_kinds = [e for e in catalog if e["namespace"] not in _BUILTIN_NAMESPACES]
    ranked = sorted(user_kinds, key=lambda e: e["attr_count"] + e["rel_count"], reverse=True)
    return [
        {"label": e["label"], "attributes": e["attr_count"], "relationships": e["rel_count"]}
        for e in ranked[:_COMPLEXITY_TOP_N]
    ]


def _filter_catalog(
    catalog: list[dict[str, Any]], filters: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Filter catalog entries by key-value pairs."""
    if not filters:
        return catalog
    result = catalog
    for key, value in filters.items():
        result = [e for e in result if e.get(key) == value]
    return result


async def _build_mermaid_str(
    client: InfrahubClient,
    branch: str | None,
    catalog: list[dict[str, Any]],
    complexity_ranking: list[dict[str, Any]],
) -> str:
    """Build Mermaid ER diagram from the top complex kinds."""
    # Get the actual catalog entries for the top complex kinds (need the kind field)
    user_kinds = [e for e in catalog if e["namespace"] not in _BUILTIN_NAMESPACES]
    ranked = sorted(user_kinds, key=lambda e: e["attr_count"] + e["rel_count"], reverse=True)
    top_entries = ranked[:_MERMAID_MAX_KINDS]
    mermaid_kinds = {e["kind"] for e in top_entries}

    lines = ["erDiagram"]
    for entry in top_entries:
        if entry["rel_count"] == 0:
            continue
        try:
            detail = await _fetch_schema_detail(client, entry["kind"], branch)
        except Exception:  # noqa: BLE001
            logger.debug("Skipping mermaid for %s", entry["kind"])
            continue
        for rel in detail["relationships"]:
            if rel["peer"] not in mermaid_kinds:
                continue
            src_label = entry["kind"].split(entry["namespace"], 1)[-1] or entry["kind"]
            peer_ns = next((e["namespace"] for e in catalog if e["kind"] == rel["peer"]), "")
            peer_label = rel["peer"].split(peer_ns, 1)[-1] if peer_ns else rel["peer"]
            peer_label = peer_label or rel["peer"]
            lines.append(f"    {src_label} ||--o{{ {peer_label} : {rel['name']}")

    if len(lines) > 1:
        return "\n".join(lines)
    return "erDiagram\n    No_relationships { }"


@app.tool()
async def fetch_overview_data(
    ctx: Context,
    branch: str | None = None,
    group_by: str = "namespace",
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Fetch data for the overview. Called on filter/group_by changes via CallTool."""
    client = get_client(ctx)

    catalog = await _fetch_schema_catalog(client, branch)
    catalog = _filter_catalog(catalog, filters)

    kinds = [e["kind"] for e in catalog]
    counts = await _fetch_node_counts(client, kinds, branch)

    namespace_data = _compute_namespace_data(catalog)
    complexity_data = _compute_complexity_ranking(catalog)
    mermaid_str = await _build_mermaid_str(client, branch, catalog, complexity_data)

    return {
        "catalog": catalog,
        "counts": counts,
        "namespace_data": namespace_data,
        "complexity_data": complexity_data,
        "mermaid_str": mermaid_str,
    }


@app.ui()
async def overview(
    ctx: Context,
    branch: str | None = None,
    group_by: str = "namespace",
    filters: dict[str, Any] | None = None,
    panels: list[dict[str, Any]] | None = None,
) -> PrefabApp:
    """Instance-level summary — namespace breakdown, schema coverage, complexity."""
    client = get_client(ctx)

    catalog = await _fetch_schema_catalog(client, branch)
    catalog = _filter_catalog(catalog, filters)

    kinds = [e["kind"] for e in catalog]
    counts = await _fetch_node_counts(client, kinds, branch)

    total_nodes = sum(c["count"] for c in counts)
    populated = [c for c in counts if c["count"] > 0]
    empty = [c for c in counts if c["count"] == 0]

    namespace_data = _compute_namespace_data(catalog)
    complexity_data = _compute_complexity_ranking(catalog)
    coverage_data = [
        {"name": "Populated", "value": len(populated)},
        {"name": "Empty", "value": len(empty)},
    ]
    distribution_data = [{"label": c["label"], "count": c["count"]} for c in populated[:20]]
    mermaid_str = await _build_mermaid_str(client, branch, catalog, complexity_data)

    with PrefabApp(
        title="Overview",
        state={
            "total_nodes": total_nodes,
            "populated_count": len(populated),
            "empty_count": len(empty),
            "namespace_data": namespace_data,
            "coverage_data": coverage_data,
            "complexity_data": complexity_data,
            "distribution_data": distribution_data,
            "mermaid_str": mermaid_str,
            "catalog_rows": catalog,
        },
    ) as prefab_app:
        with Tabs(value="summary"):
            with Tab("Summary"):
                with Column():
                    with Grid(columns=3):
                        Metric(label="Total Nodes", value=Rx("total_nodes"))
                        Metric(label="Populated Kinds", value=Rx("populated_count"))
                        Metric(label="Empty Kinds", value=Rx("empty_count"))
                    H3(content="Namespace Distribution")
                    PieChart(data=Rx("namespace_data"), data_key="value", name_key="name")
                    H3(content="Schema Coverage")
                    PieChart(data=Rx("coverage_data"), data_key="value", name_key="name")
            with Tab("Distribution"):
                with Column():
                    H3(content="Top Kinds by Node Count")
                    BarChart(
                        data=Rx("distribution_data"),
                        x_axis="label",
                        series=[ChartSeries(data_key="count")],
                    )
            with Tab("Complexity"):
                with Column():
                    H3(content="Top Kinds by Field Count")
                    BarChart(
                        data=Rx("complexity_data"),
                        x_axis="label",
                        series=[
                            ChartSeries(data_key="attributes"),
                            ChartSeries(data_key="relationships"),
                        ],
                        stacked=True,
                    )
            with Tab("Relationships"):
                with Column():
                    H3(content="Entity Relationship Diagram")
                    Mermaid(chart=Rx("mermaid_str"))
            with Tab("Catalog"):
                DataTable(
                    columns=_CATALOG_TABLE_COLUMNS,
                    rows=Rx("catalog_rows"),  # type: ignore[arg-type]
                    paginated=True,
                    page_size=10,
                )
    return prefab_app
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_app_overview.py -v`
Expected: PASS

- [ ] **Step 5: Run full suite and linters**

Run: `uv run pytest tests/ -v && uv run pre-commit run --all-files`
Expected: All PASS.

- [ ] **Step 6: Commit**

```bash
git add src/infrahub_app/overview.py tests/unit/test_app_overview.py
git commit -m "feat: add overview tool with namespace, coverage, complexity, and ER diagram"
```

---

### Task 6: Final integration — verify everything works together

**Files:**
- None new — verification only

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS. No references to deleted `reports/` module.

- [ ] **Step 2: Run all linters**

Run: `uv run pre-commit run --all-files`
Expected: PASS.

- [ ] **Step 3: Run mypy**

Run: `uv run invoke lint-mypy`
Expected: PASS with no errors related to `infrahub_app` or `infrahub_mcp.reports`.

- [ ] **Step 4: Verify the package can be imported end-to-end**

Run: `uv run python -c "from infrahub_app import app; print(app.name, type(app).__name__)"`
Expected: `Infrahub FastMCPApp`

- [ ] **Step 5: Verify server.py imports cleanly**

Run: `uv run python -c "import infrahub_mcp.server; print('server imports OK')"`
Expected: May fail due to env var validation (`INFRAHUB_ADDRESS` required). That's fine — just verify no `ImportError`.

If it fails with `RuntimeError: INFRAHUB_ADDRESS is required`, that's the expected validation. The import chain is working.

- [ ] **Step 6: Commit (if any lint fixes were needed)**

```bash
git add -A
git commit -m "chore: lint fixes for infrahub_app integration"
```

Only commit if there were actual changes. Skip if everything was clean.
