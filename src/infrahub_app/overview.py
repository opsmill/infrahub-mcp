"""Overview tool — instance-level summary with namespace, coverage, and complexity views."""

from __future__ import annotations

import asyncio
import logging
import operator
from collections import Counter
from typing import TYPE_CHECKING, Any

from fastmcp import Context  # noqa: TC002
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    Card,
    CardContent,
    CardDescription,
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
) -> str:
    """Build Mermaid ER diagram from the top complex kinds."""
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
    group_by: str = "namespace",  # noqa: ARG001
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
    mermaid_str = await _build_mermaid_str(client, branch, catalog)

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
    group_by: str = "namespace",  # noqa: ARG001
    filters: dict[str, Any] | None = None,
    panels: list[dict[str, Any]] | None = None,  # noqa: ARG001
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
    mermaid_str = await _build_mermaid_str(client, branch, catalog)

    # Compute summary stats
    total_kinds = len(catalog)
    ns_count = len({e["namespace"] for e in catalog})
    user_kinds = len([e for e in catalog if e["namespace"] not in _BUILTIN_NAMESPACES])

    with PrefabApp(
        title="Overview",
        state={
            "total_nodes": total_nodes,
            "total_kinds": total_kinds,
            "ns_count": ns_count,
            "user_kinds": user_kinds,
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
                with Column(gap=4):
                    # KPI metric cards
                    with Grid(columns=4, gap=4):
                        with Card():
                            with CardContent():
                                Metric(label="Total Nodes", value=Rx("total_nodes"))
                        with Card():
                            with CardContent():
                                Metric(label="Total Kinds", value=Rx("total_kinds"))
                        with Card():
                            with CardContent():
                                Metric(label="Populated Kinds", value=Rx("populated_count"))
                        with Card():
                            with CardContent():
                                Metric(label="Namespaces", value=Rx("ns_count"))

                    # Namespace + Coverage side by side
                    with Grid(columns=2, gap=4):
                        with Card():
                            with CardHeader():
                                CardTitle("Namespaces")
                                CardDescription("Kind distribution by namespace")
                            with CardContent():
                                PieChart(  # type: ignore[call-arg]
                                    data=Rx("namespace_data"),
                                    data_key="value",
                                    name_key="name",
                                    inner_radius=60,
                                    height=250,
                                    show_legend=True,
                                )
                        with Card():
                            with CardHeader():
                                CardTitle("Schema Coverage")
                                CardDescription("Populated vs empty kinds")
                            with CardContent():
                                PieChart(  # type: ignore[call-arg]
                                    data=Rx("coverage_data"),
                                    data_key="value",
                                    name_key="name",
                                    inner_radius=60,
                                    height=250,
                                    show_legend=True,
                                )

            with Tab("Distribution"):
                with Card():
                    with CardHeader():
                        CardTitle("Top Kinds by Node Count")
                        CardDescription("Most populated kinds in this instance")
                    with CardContent():
                        BarChart(  # type: ignore[call-arg]
                            data=Rx("distribution_data"),
                            x_axis="label",
                            series=[ChartSeries(data_key="count")],  # type: ignore[call-arg]
                            height=350,
                        )

            with Tab("Complexity"):
                with Card():
                    with CardHeader():
                        CardTitle("Schema Complexity")
                        CardDescription("User-defined kinds ranked by total fields (excluding builtins)")
                    with CardContent():
                        with Column(gap=2):
                            Muted(f"{user_kinds} user-defined kinds", css_class="text-sm")
                            Separator()
                            BarChart(  # type: ignore[call-arg]
                                data=Rx("complexity_data"),
                                x_axis="label",
                                series=[
                                    ChartSeries(data_key="attributes", label="Attributes"),  # type: ignore[call-arg]
                                    ChartSeries(data_key="relationships", label="Relationships"),  # type: ignore[call-arg]
                                ],
                                stacked=True,
                                height=350,
                            )

            with Tab("Relationships"):
                with Card():
                    with CardHeader():
                        CardTitle("Entity Relationship Diagram")
                        CardDescription("Top complex kinds and their relationships")
                    with CardContent():
                        Mermaid(chart=Rx("mermaid_str"))

            with Tab("Catalog"):
                with Card():
                    with CardHeader():
                        with Row(align="center", css_class="justify-between"):
                            CardTitle("Schema Catalog")
                            Muted(f"{total_kinds} kinds")
                    with CardContent():
                        DataTable(
                            columns=_CATALOG_TABLE_COLUMNS,
                            rows=Rx("catalog_rows"),  # type: ignore[arg-type]
                            paginated=True,
                            page_size=15,
                            search=True,
                        )
    return prefab_app
