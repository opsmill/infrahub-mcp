"""Explore tool — visualize nodes of a single kind with auto-detected or custom charts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastmcp import Context  # noqa: TC002
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
from prefab_ui.components.charts import PieChart
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
                        PieChart(data=panel_item.data, data_key="count", name_key="name")  # type: ignore[call-arg]
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
