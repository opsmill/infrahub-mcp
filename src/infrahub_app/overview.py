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
                    PieChart(data=Rx("namespace_data"), data_key="value", name_key="name")  # type: ignore[call-arg]
                    H3(content="Schema Coverage")
                    PieChart(data=Rx("coverage_data"), data_key="value", name_key="name")  # type: ignore[call-arg]
            with Tab("Distribution"):
                with Column():
                    H3(content="Top Kinds by Node Count")
                    BarChart(  # type: ignore[call-arg]
                        data=Rx("distribution_data"),
                        x_axis="label",
                        series=[ChartSeries(data_key="count")],
                    )
            with Tab("Complexity"):
                with Column():
                    H3(content="Top Kinds by Field Count")
                    BarChart(  # type: ignore[call-arg]
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
