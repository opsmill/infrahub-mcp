"""Explore tool — visualize nodes of a single kind with auto-detected or custom charts."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastmcp import Context  # noqa: TC002
from fastmcp.exceptions import ToolError
from infrahub_sdk.exceptions import SchemaNotFoundError
from prefab_ui.actions.mcp import CallTool
from prefab_ui.actions.state import SetState
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    Column,
    Combobox,
    ComboboxOption,
    DataTable,
    DataTableColumn,
    Grid,
    Metric,
    Muted,
    Row,
    Separator,
    Tab,
    Tabs,
)
from prefab_ui.components.charts import BarChart, ChartSeries, PieChart
from prefab_ui.components.control_flow.foreach import ForEach
from prefab_ui.rx import EVENT, RESULT, Rx

from infrahub_app.app import Filters, app, get_client
from infrahub_app.panels import PanelConfig, auto_detect_panels, compute_distribution, refine_chart_type
from infrahub_mcp.utils import convert_node_to_dict

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient

logger = logging.getLogger(__name__)


async def _validate_kind(client: InfrahubClient, kind: str, branch: str | None = None) -> str:
    """Validate that a kind exists and return its canonical name.

    Raises ToolError with a list of valid kinds when the kind is not found.
    """
    try:
        schema = await client.schema.get(kind=kind, branch=branch)
        return schema.kind
    except SchemaNotFoundError:
        all_schemas = await client.schema.all(branch=branch)
        valid = ", ".join(sorted(all_schemas.keys()))
        msg = f"Kind '{kind}' not found.\n\nValid kinds: {valid}"
        raise ToolError(msg) from None


async def _fetch_schema_detail(
    client: InfrahubClient, kind: str, branch: str | None = None,
) -> dict[str, Any]:
    """Fetch detailed schema for a kind, including peer kind for relationships."""
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
    if filters:
        nodes = await client.filters(
            kind=kind, branch=branch, limit=limit, populate_store=True, **filters,
        )
    else:
        nodes = await client.all(kind=kind, branch=branch, limit=limit, populate_store=True)
    rows: list[dict[str, Any]] = []
    for node in nodes:
        row = await convert_node_to_dict(obj=node, branch=branch, hfid_include_kind=False)
        rows.append(row)
    return rows, column_names


def _build_rel_label_map(schema: dict[str, Any]) -> dict[str, str]:
    """Build a mapping from relationship name to a display label including peer kind.

    Example: "member_of_groups" with peer "CoreStandardGroup" → "member_of_groups (CoreStandardGroup)"
    """
    return {
        rel["name"]: f"{rel['name']} ({rel['peer']})"
        for rel in schema.get("relationships", [])
    }


def _compute_distributions(
    nodes: list[dict[str, Any]],
    panels: list[PanelConfig],
    rel_labels: dict[str, str],
) -> list[dict[str, Any]]:
    """Compute distribution data for each panel's field, refining chart types based on data."""
    total_nodes = len(nodes)
    result: list[dict[str, Any]] = []
    for panel in panels:
        limit = panel.options.get("limit", 20)
        dist = compute_distribution(nodes, panel.field, limit=limit)
        if dist:
            chart_type = refine_chart_type(panel.type, dist, total_nodes)
            label = rel_labels.get(panel.field, panel.field)
            result.append({"field": label, "type": chart_type, "data": dist})
    return result


async def _build_explore_state(
    client: InfrahubClient,
    kind: str,
    branch: str | None = None,
    filters: dict[str, Any] | None = None,
    panels: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the complete UI state for a given kind."""
    schema = await _fetch_schema_detail(client, kind, branch)
    nodes, _columns = await _fetch_nodes_for_kind(client, kind, branch, filters)

    panel_configs = [PanelConfig.from_dict(p) for p in panels] if panels else auto_detect_panels(schema)
    rel_labels = _build_rel_label_map(schema)
    distributions = _compute_distributions(nodes, panel_configs, rel_labels)

    pie_panels = [d for d in distributions if d["type"] == "pie"]
    bar_panels = [d for d in distributions if d["type"] == "bar"]

    return {
        "node_count": len(nodes),
        "attr_count": len(schema["attributes"]),
        "rel_count": len(schema["relationships"]),
        "pie_panels": pie_panels,
        "bar_panels": bar_panels,
        "table_rows": nodes,
    }


@app.tool()
async def fetch_explore_data(
    kind: str,
    ctx: Context,
    branch: str | None = None,
    filters: Filters = None,
) -> dict[str, Any]:
    """Fetch explore data for a kind. Returns UI state for reactive updates."""
    client = get_client(ctx)
    kind = await _validate_kind(client, kind, branch)
    return await _build_explore_state(client, kind, branch, filters)


@app.ui()
async def explore(
    ctx: Context,
    kind: str | None = None,
    branch: str | None = None,
    filters: Filters = None,
    panels: list[dict[str, Any]] | None = None,
) -> PrefabApp:
    """Visualize nodes of a single kind with auto-detected or custom charts."""
    client = get_client(ctx)

    # Fetch all available kinds for the Combobox picker
    all_schemas = await client.schema.all(branch=branch)
    available_kinds = sorted(all_schemas.keys())

    # If kind provided, validate and fetch data; otherwise start empty
    if kind:
        kind = await _validate_kind(client, kind, branch)
        state = await _build_explore_state(client, kind, branch, filters, panels)
    else:
        state = {
            "node_count": 0,
            "attr_count": 0,
            "rel_count": 0,
            "pie_panels": [],
            "bar_panels": [],
            "table_rows": [],
        }

    # Build dynamic table columns (from initial kind, or empty)
    table_col_defs: list[DataTableColumn] = []
    if kind:
        _, columns = await _fetch_nodes_for_kind(client, kind, branch, filters, limit=0)
        table_col_defs = [
            DataTableColumn(key=c, header=c.replace("_", " ").title(), sortable=True)
            for c in columns
        ]

    # Action chain: Combobox change → fetch data → update all state keys
    on_kind_change = CallTool(
        fetch_explore_data,
        arguments={"kind": EVENT, "branch": branch or ""},
        on_success=[
            SetState("node_count", RESULT["node_count"]),
            SetState("attr_count", RESULT["attr_count"]),
            SetState("rel_count", RESULT["rel_count"]),
            SetState("pie_panels", RESULT["pie_panels"]),
            SetState("bar_panels", RESULT["bar_panels"]),
            SetState("table_rows", RESULT["table_rows"]),
        ],
    )

    with PrefabApp(
        title=f"Explore: {kind}" if kind else "Explore",
        state={"selected_kind": kind or "", **state},
    ) as prefab_app:
        with Column(gap=4):
            # Kind picker
            with Card():
                with CardHeader():
                    CardTitle("Kind")
                    CardDescription("Select a node kind to explore")
                with CardContent():
                    with Combobox(
                        name="selected_kind",
                        placeholder="Search kinds...",
                        search_placeholder="Type to filter...",
                        on_change=on_kind_change,
                    ):
                        for k in available_kinds:
                            label = all_schemas[k].label or k
                            ComboboxOption(f"{label} ({k})" if label != k else k, value=k)

            # Dashboard content
            with Tabs(value="overview"):
                with Tab("Overview"):
                    with Column(gap=4):
                        with Grid(columns=3, gap=4):
                            with Card():
                                with CardContent():
                                    Metric(label="Nodes", value=Rx("node_count"))
                            with Card():
                                with CardContent():
                                    Metric(label="Attributes", value=Rx("attr_count"))
                            with Card():
                                with CardContent():
                                    Metric(label="Relationships", value=Rx("rel_count"))

                        # Pie charts — always in tree, ForEach handles empty
                        with Card():
                            with CardHeader():
                                CardTitle("Distributions")
                                CardDescription("Attribute and relationship value breakdown")
                            with CardContent():
                                with ForEach(Rx("pie_panels")) as (_idx, panel_item):
                                    with Column(gap=1):
                                        Muted(panel_item.field, css_class="text-sm font-medium text-center")
                                        PieChart(  # type: ignore[call-arg]
                                            data=panel_item.data,
                                            data_key="count",
                                            name_key="name",
                                            inner_radius=50,
                                            height=220,
                                            show_legend=True,
                                        )

                        # Bar charts — always in tree, ForEach handles empty
                        with Card():
                            with CardHeader():
                                CardTitle("Counts")
                                CardDescription("Numeric and relationship count distributions")
                            with CardContent():
                                with ForEach(Rx("bar_panels")) as (_idx2, bar_item):
                                    with Column(gap=1):
                                        Muted(bar_item.field, css_class="text-sm font-medium")
                                        BarChart(  # type: ignore[call-arg]
                                            data=bar_item.data,
                                            x_axis="name",
                                            series=[ChartSeries(data_key="count")],  # type: ignore[call-arg]
                                            height=250,
                                        )
                                        Separator()

                with Tab("Data"):
                    with Card():
                        with CardHeader():
                            with Row(align="center", css_class="justify-between"):
                                CardTitle("Node Data")
                                Muted(f"{state['node_count']} records")
                        with CardContent():
                            if table_col_defs:
                                DataTable(
                                    columns=table_col_defs,
                                    rows=Rx("table_rows"),  # type: ignore[arg-type]
                                    paginated=True,
                                    page_size=15,
                                    search=True,
                                )
                            else:
                                Muted("Select a kind to view data.", css_class="text-sm py-8 text-center")
    return prefab_app
