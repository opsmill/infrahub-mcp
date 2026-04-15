"""Explore tool — visualize nodes of a single kind with auto-detected or custom charts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastmcp import Context  # noqa: TC002
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Column,
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
from prefab_ui.rx import Rx

from infrahub_app.app import app, get_client
from infrahub_app.panels import PanelConfig, auto_detect_panels, compute_distribution
from infrahub_mcp.utils import convert_node_to_dict

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient


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
    panel_configs = [PanelConfig.from_dict(p) for p in panels] if panels else auto_detect_panels(schema)

    distributions = _compute_distributions(nodes, panel_configs)

    # Split distributions by chart type for proper rendering
    pie_panels = [d for d in distributions if d["type"] == "pie"]
    bar_panels = [d for d in distributions if d["type"] == "bar"]

    # Build dynamic table columns from actual schema
    table_col_defs = [
        DataTableColumn(key=c, header=c.replace("_", " ").title(), sortable=True)
        for c in columns
    ]

    # Compute active filters description
    filter_desc = ""
    if filters:
        filter_desc = ", ".join(f"{k}={v}" for k, v in filters.items())

    with PrefabApp(
        title=f"Explore: {kind}",
        state={
            "node_count": len(nodes),
            "attr_count": len(schema["attributes"]),
            "rel_count": len(schema["relationships"]),
            "pie_panels": pie_panels,
            "bar_panels": bar_panels,
            "table_rows": nodes,
        },
    ) as prefab_app:
        with Tabs(value="overview"):
            with Tab("Overview"):
                with Column(gap=4):
                    # Metric cards in Card containers
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

                    if filter_desc:
                        Muted(f"Filtered: {filter_desc}", css_class="text-sm")

                    # Pie charts — attribute/relationship distributions (donut style)
                    if pie_panels:
                        with Card():
                            with CardHeader():
                                CardTitle("Distributions")
                                Muted("Attribute and relationship value breakdown")
                            with CardContent():
                                with Grid(columns=min(len(pie_panels), 3), gap=4):
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

                    # Bar charts — numeric/many-relationship distributions
                    if bar_panels:
                        with Card():
                            with CardHeader():
                                CardTitle("Counts")
                                Muted("Numeric and relationship count distributions")
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
                            Muted(f"{len(nodes)} records")
                    with CardContent():
                        DataTable(
                            columns=table_col_defs,
                            rows=Rx("table_rows"),  # type: ignore[arg-type]
                            paginated=True,
                            page_size=15,
                            search=True,
                        )
    return prefab_app
