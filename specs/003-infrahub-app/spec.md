# Spec 003: Infrahub App (FastMCPApp)

**Date:** 2026-04-15
**Status:** Draft
**Scope:** Spec 1 of 2 — `explore` + `overview` + app skeleton + delete old `reports/`

Spec 2 (later): `proposed_change` tool, `create` tool, service workflow demo.

## Problem

The current `reports/` module bakes domain-specific dashboards into the MCP server. This couples visualization logic to the data API, limits reusability across different Infrahub instances, and doesn't follow the FastMCPApp pattern from Prefab.

## Architecture

Three layers, matching the Hitchhiker's Guide pattern:

```
Standalone App (domain-specific)
    ↓ calls
FastMCPApp "Infrahub" (generic, schema-agnostic)
    ↓ uses
MCP Server (pure data/action API)
```

- **MCP Server** (existing, unchanged): `get_nodes`, `get_schema`, `node_upsert`, `query_graphql`, etc.
- **MCP App** (new `FastMCPApp`): Generic visualization tools that work on ANY Infrahub instance. Fetches data via SDK client from Context, renders as Prefab components.
- **Standalone App** (example): Domain-specific dashboards built by users for their instance. We provide one example.

## Package Structure

New package `src/infrahub_app/` (separate from `infrahub_mcp`, treated as a distinct package even though it lives in the same repo for now):

```
src/infrahub_app/
├── __init__.py            # exports `app` for mounting
├── app.py                 # FastMCPApp("Infrahub") instance
├── explore.py             # @app.ui() explore + @app.tool() fetch_explore_data
├── overview.py            # @app.ui() overview + @app.tool() fetch_overview_data
└── panels.py              # Panel config parsing + chart builder logic

examples/
└── dashboard_app.py       # Standalone demo (static HTML export)
```

### Delete

Remove entirely:

- `src/infrahub_mcp/reports/` (all files: `__init__.py`, `reports.py`, `fetchers.py`, `charts.py`, `store.py`)
- `tests/unit/test_report_reports.py`, `tests/unit/test_report_fetchers.py`, and any other `test_report_*.py` files
- Remove `reports_mcp` mount from `server.py`
- Remove mypy overrides for `infrahub_mcp.reports.*` from `pyproject.toml`

### Mount

In `server.py`, mount the app via:

```python
from infrahub_app import app as infrahub_app
mcp.mount(infrahub_app)
```

## Tool: `explore`

**Purpose:** Visualize nodes of a single kind with auto-detected or custom charts.

### Signature

```python
@app.ui()
async def explore(
    kind: str,
    ctx: Context,
    branch: str | None = None,
    filters: dict[str, Any] | None = None,
    panels: list[dict[str, Any]] | None = None,
) -> PrefabApp:
```

### Parameters

| Parameter | Type | Description |
|---|---|---|
| `kind` | `str` | Schema kind to explore (e.g., `"InfraDevice"`) |
| `branch` | `str \| None` | Branch name, defaults to main |
| `filters` | `dict \| None` | Key-value filters passed to `get_nodes` (e.g., `{"status__value": "active"}`) |
| `panels` | `list[dict] \| None` | Panel configs. Omit for auto-detect. |

### Panel Config Format

Each panel is a dict:

```python
{
    "type": "pie" | "bar" | "line" | "area" | "metric" | "table",
    "field": "status",          # attribute or relationship name
    "options": {                 # optional, type-specific
        "horizontal": True,     # bar only
        "stacked": True,        # bar only
        "series": ["attr1", "attr2"],  # multi-series bar
        "limit": 10,            # top-N for distributions
    }
}
```

### Auto-detect Logic (when `panels` is omitted)

1. Fetch schema detail for the kind
2. For each attribute:
   - `Dropdown` kind -> pie chart
   - `Boolean` kind -> pie chart
   - `Number`/`Integer` kind -> bar chart (distribution buckets)
   - Other -> skip
3. For each relationship:
   - Cardinality `one` -> pie chart (peer distribution)
   - Cardinality `many` -> bar chart (count distribution)
4. Always include a summary metric row (node count, attribute count, relationship count)
5. Always include a data table tab with all nodes

### Layout

```
Tabs:
  "Overview":
    Grid(columns=3): Metric cards (node count, attributes, relationships)
    ForEach panel: chart component
  "Data":
    DataTable (all nodes, paginated, sortable)
```

### Backend Tool

```python
@app.tool()
async def fetch_explore_data(
    kind: str,
    ctx: Context,
    branch: str | None = None,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
```

Returns `{ nodes, columns, schema, distributions }`. Called by UI on filter changes via `CallTool` + `SetState`.

## Tool: `overview`

**Purpose:** Instance-level summary — how many nodes per kind, namespace breakdown, schema coverage.

### Signature

```python
@app.ui()
async def overview(
    ctx: Context,
    branch: str | None = None,
    group_by: str = "namespace",
    filters: dict[str, Any] | None = None,
    panels: list[dict[str, Any]] | None = None,
) -> PrefabApp:
```

### Parameters

| Parameter | Type | Description |
|---|---|---|
| `branch` | `str \| None` | Branch name |
| `group_by` | `str` | Grouping dimension: `"namespace"` (default), `"label"`, `"kind"` |
| `filters` | `dict \| None` | Filter the catalog of kinds (e.g., `{"namespace": "Infra"}` to show only Infra kinds) |
| `panels` | `list[dict] \| None` | Panel configs. Omit for auto-detect. |

### Auto-detect Logic (when `panels` is omitted)

1. Fetch schema catalog + node counts for all kinds
2. Generate:
   - Pie chart: namespace distribution
   - Pie chart: schema coverage (populated vs empty kinds)
   - Bar chart: top-20 kinds by node count
   - Bar chart: top-20 kinds by complexity (attr_count + rel_count), excluding builtins
   - Mermaid ER diagram: relationship map of top-30 complex kinds

### Layout

```
Tabs:
  "Summary":
    Grid(columns=3): Metric cards (total nodes, populated kinds, empty kinds)
    Pie: namespace distribution
    Pie: coverage
  "Distribution":
    Bar: top kinds by node count
  "Complexity":
    Bar: top kinds by field count (stacked: attributes vs relationships)
  "Relationships":
    Mermaid ER diagram
  "Catalog":
    DataTable (all kinds, paginated, sortable)
```

### Backend Tool

```python
@app.tool()
async def fetch_overview_data(
    ctx: Context,
    branch: str | None = None,
    group_by: str = "namespace",
    filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
```

Returns `{ catalog, counts, namespace_data, complexity_data, mermaid_str }`. Called on filter/group_by changes.

## Panel Engine (`panels.py`)

Centralized logic for building charts from panel configs.

### Responsibilities

1. **Parse panel configs** — validate type, field, options
2. **Auto-detect panels** — given a schema, generate sensible panel configs
3. **Build chart components** — given panel config + data, return Prefab component tree

### Key Functions

```python
def auto_detect_panels(schema: dict, nodes: list[dict]) -> list[PanelConfig]:
    """Introspect schema and return sensible panel configs."""

def build_panel(panel: PanelConfig, data: list[dict]) -> Component:
    """Given a panel config and data, return a Prefab chart component."""

def compute_distribution(nodes: list[dict], field: str, limit: int = 20) -> list[dict]:
    """Count occurrences of each value for a field. Return sorted top-N."""
```

### PanelConfig

```python
@dataclass
class PanelConfig:
    type: str          # "pie", "bar", "line", "area", "metric", "table"
    field: str         # attribute or relationship name
    options: dict      # type-specific options (horizontal, stacked, series, limit)
```

### Chart Type Mapping

| Panel Type | Prefab Component | Key Options |
|---|---|---|
| `pie` | `PieChart` | `data_key`, `name_key` |
| `bar` | `BarChart` | `horizontal`, `stacked`, `series` (multi-series) |
| `line` | `LineChart` | `series` |
| `area` | `AreaChart` | `series`, `stacked` |
| `metric` | `Metric` | `label`, `value` |
| `table` | `DataTable` | columns auto-derived from data keys |

## Interactivity & CallTool Flow

UI controls (filter dropdowns, group_by selectors) trigger backend re-fetch via Prefab's `CallTool` + `SetState` pattern:

```
User changes filter in UI
  → CallTool("fetch_explore_data", {kind, branch, filters: new_filters})
  → on_success: SetState(nodes=result.nodes, distributions=result.distributions)
  → ForEach / charts re-render with new state
```

This means:
- `@app.ui()` functions build the initial view and state
- `@app.tool()` functions are the backend endpoints for re-fetching data
- Prefab handles the reactive update cycle

## Data Access

Backend tools (`fetch_explore_data`, `fetch_overview_data`) access the Infrahub SDK client directly via `ctx.request_context.lifespan_context.client`, same pattern as the current `reports/` module. No MCP-over-MCP indirection.

## Testing Strategy

- **Unit tests** for `panels.py`: auto-detect logic, distribution computation, chart building
- **Unit tests** for `explore` and `overview`: mock SDK client, verify PrefabApp structure and state
- **Same pattern** as current `test_report_reports.py`: patch fetcher functions, assert on returned PrefabApp

## Out of Scope (Spec 2)

- `proposed_change` tool — branch/pipeline monitoring with status tracking
- `create` tool — form-based node creation with branch workflow
- Service workflow demo (inspired by `infrahub-demo-service-catalog`)
- Standalone `examples/dashboard_app.py` (depends on the above)
