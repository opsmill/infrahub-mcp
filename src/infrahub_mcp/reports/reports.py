"""MCP tool endpoints that wire together store, fetchers, and chart builders into PrefabApps.

Each public tool creates a report in the store, launches a background task, and
returns a PrefabApp immediately.  The PrefabApp polls ``get_report_state`` via
SetInterval and updates reactively via Rx.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from typing import TYPE_CHECKING, Any

from fastmcp import Context, FastMCP
from prefab_ui.actions.mcp import CallTool
from prefab_ui.actions.state import SetState
from prefab_ui.actions.timing import SetInterval
from prefab_ui.app import PrefabApp
from prefab_ui.components import (
    H3,
    Alert,
    AlertDescription,
    AlertTitle,
    Column,
    DataTable,
    DataTableColumn,
    Grid,
    Metric,
    P,
    Progress,
    Tab,
    Tabs,
)
from prefab_ui.components.charts import BarChart, ChartSeries, PieChart
from prefab_ui.components.control_flow.conditional import Elif, Else, If
from prefab_ui.components.control_flow.foreach import ForEach
from prefab_ui.components.mermaid import Mermaid
from prefab_ui.rx import Rx

from infrahub_mcp.reports.fetchers import (
    compute_field_distributions,
    compute_relationship_distributions,
    fetch_node_counts,
    fetch_nodes_for_kind,
    fetch_schema_catalog,
    fetch_schema_detail,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from infrahub_sdk.client import InfrahubClient

    from infrahub_mcp.reports.store import ReportStore
    from infrahub_mcp.utils import AppContext

logger = logging.getLogger(__name__)

mcp = FastMCP("Infrahub Analytics Reports")

# ---------------------------------------------------------------------------
# Background task management
# ---------------------------------------------------------------------------

_background_tasks: set[asyncio.Task[None]] = set()


def _launch_background(coro: Coroutine[Any, Any, None]) -> None:
    """Schedule a coroutine as a fire-and-forget background task."""
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


# ---------------------------------------------------------------------------
# Context helpers
# ---------------------------------------------------------------------------


def _get_app_ctx(ctx: Context) -> AppContext:
    return ctx.request_context.lifespan_context  # type: ignore[union-attr,return-value]


def _get_client(ctx: Context) -> InfrahubClient:
    return _get_app_ctx(ctx).client


def _get_store(ctx: Context) -> ReportStore:
    return _get_app_ctx(ctx).report_store  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Shared UI builder helpers
# ---------------------------------------------------------------------------

_POLL_INTERVAL_MS = 1500


def _build_polling_app(title: str, report_id: str) -> PrefabApp:
    """Build the skeleton PrefabApp with polling wired up.

    The caller adds body content via ``with app:`` after this returns.
    """
    return PrefabApp(
        title=title,
        state={
            "status": "running",
            "progress": 0,
            "status_message": "",
            "result": None,
            "error": None,
        },
        on_mount=SetInterval(
            duration=_POLL_INTERVAL_MS,
            while_=Rx("status") == "running",
            onTick=CallTool(
                tool="get_report_state",
                arguments={"report_id": report_id},
                onSuccess=[
                    SetState("status", Rx("result.status")),
                    SetState("progress", Rx("result.progress")),
                    SetState("status_message", Rx("result.status_message")),
                    SetState("result", Rx("result.result")),
                    SetState("error", Rx("result.error")),
                ],
            ),
        ),
    )


def _add_loading_state() -> None:
    """Add loading-state UI inside an open If block."""
    with Column():
        Progress(value=Rx("progress"), max=1.0)
        P(content=Rx("status_message"))


def _add_error_state() -> None:
    """Add error-state UI inside an open Else block."""
    with Alert(variant="destructive"):
        AlertTitle("Error")
        AlertDescription(content=Rx("error"))


# ---------------------------------------------------------------------------
# Hidden polling tool
# ---------------------------------------------------------------------------


@mcp.tool(annotations={"readOnlyHint": True})
async def get_report_state(report_id: str, ctx: Context) -> dict[str, Any]:
    """Get current state of a report for UI polling."""
    store = _get_store(ctx)
    report = await store.get(report_id)
    if report is None:
        return {
            "status": "error",
            "error": "Report not found",
            "progress": 0,
            "status_message": "",
            "result": None,
        }
    return {
        "status": report.status.value,
        "progress": report.progress,
        "status_message": report.status_message,
        "result": report.result,
        "error": report.error,
    }


# ---------------------------------------------------------------------------
# Report 1: kind_report
# ---------------------------------------------------------------------------

# Generic columns for the kind_report Data tab.  Actual columns depend on
# the schema, but DataTable requires a static column list at build time.
# These cover the attributes present on virtually every Infrahub node.
_KIND_REPORT_TABLE_COLUMNS = [
    DataTableColumn(key="name", header="Name", sortable=True),
    DataTableColumn(key="description", header="Description", sortable=True),
]

_CHARTABLE_ATTR_KINDS = {"Dropdown", "Boolean"}


def _detect_chartable_attributes(
    attributes: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return attributes likely to produce meaningful charts."""
    return [
        attr
        for attr in attributes
        if attr.get("kind") in _CHARTABLE_ATTR_KINDS
        or attr.get("kind") == "Text"
    ]


def _format_distributions(
    distributions: list[dict[str, Any]],
    value_key: str = "name",
    count_key: str = "value",
) -> list[dict[str, Any]]:
    """Re-shape distribution dicts for chart consumption."""
    return [
        {
            "field": fd["field"],
            "data": [
                {value_key: d["value"], count_key: d["count"]}
                for d in fd["distribution"]
            ],
        }
        for fd in distributions
    ]


async def _run_kind_report(
    store: ReportStore,
    client: InfrahubClient,
    report_id: str,
    kind: str,
    branch: str | None,
) -> None:
    """Background task for the kind_report tool."""
    try:
        await store.update_progress(report_id, 0.1, f"Fetching schema for {kind}...")
        schema = await fetch_schema_detail(client, kind, branch)

        await store.update_progress(report_id, 0.2, "Detecting chartable fields...")
        attributes = schema["attributes"]
        relationships = schema["relationships"]

        await store.update_progress(report_id, 0.5, f"Fetching nodes for {kind}...")
        nodes, columns = await fetch_nodes_for_kind(client, kind, branch)

        await store.update_progress(report_id, 0.7, "Computing field distributions...")
        field_distributions = compute_field_distributions(nodes, attributes)

        await store.update_progress(report_id, 0.9, "Computing relationship distributions...")
        rel_distributions = compute_relationship_distributions(nodes, relationships)

        # Build result for PrefabApp layout
        result = {
            "node_count": len(nodes),
            "attr_count": len(attributes),
            "rel_count": len(relationships),
            "field_charts": _format_distributions(
                field_distributions, "name", "value",
            ),
            "rel_charts": _format_distributions(
                rel_distributions, "label", "count",
            ),
            "table_rows": nodes,
            "table_columns": [
                {"key": c, "header": c.replace("_", " ").title()}
                for c in columns
            ],
        }
        await store.complete(report_id, result)
    except Exception as exc:
        logger.exception("kind_report failed for %s", kind)
        await store.fail(report_id, str(exc))


def _build_kind_overview_tab() -> None:
    """Build the Overview tab content for the kind_report."""
    with Column():
        with Grid(columns=3):
            Metric(label="Nodes", value=Rx("result.node_count"))
            Metric(label="Attributes", value=Rx("result.attr_count"))
            Metric(label="Relationships", value=Rx("result.rel_count"))
        H3(content="Field Distributions")
        with ForEach(Rx("result.field_charts")) as (_idx, chart):
            P(content=Rx(f"{chart}.field"))
            PieChart(data=Rx(f"{chart}.data"), data_key="value", name_key="name")
        H3(content="Relationship Distributions")
        with ForEach(Rx("result.rel_charts")) as (_idx2, rel_chart):
            P(content=Rx(f"{rel_chart}.field"))
            BarChart(
                data=Rx(f"{rel_chart}.data"),
                x_axis="label",
                series=[ChartSeries(data_key="count")],
            )


def _build_kind_data_tab() -> None:
    """Build the Data tab content for the kind_report."""
    with Column():
        H3(content="Node Data")
        DataTable(
            columns=_KIND_REPORT_TABLE_COLUMNS,
            rows=Rx("result.table_rows"),  # type: ignore[arg-type]
            paginated=True,
            page_size=10,
        )


@mcp.tool(app=True)
async def kind_report(kind: str, ctx: Context, branch: str | None = None) -> PrefabApp:
    """Generate a visual report for any schema kind with auto-detected charts."""
    store = _get_store(ctx)
    client = _get_client(ctx)
    report = await store.create(f"Kind Report: {kind}")

    _launch_background(_run_kind_report(store, client, report.id, kind, branch))

    app = _build_polling_app(f"Kind Report: {kind}", report.id)
    with app:
        with If(condition=Rx("status") == "running"):
            _add_loading_state()
        with Elif(condition=Rx("status") == "ready"):
            with Tabs(value="overview"):
                with Tab("Overview"):
                    _build_kind_overview_tab()
                with Tab("Data"):
                    _build_kind_data_tab()
        with Else():
            _add_error_state()
    return app


# ---------------------------------------------------------------------------
# Report 2: schema_report
# ---------------------------------------------------------------------------

_SCHEMA_COMPLEXITY_TOP_N = 20
_MERMAID_MAX_KINDS = 30
_BUILTIN_NAMESPACES = {"Core", "Builtin", "Internal", "Lineage", "Profile"}

# Static column definitions for schema_report Catalog tab.
_CATALOG_TABLE_COLUMNS = [
    DataTableColumn(key="kind", header="Kind", sortable=True),
    DataTableColumn(key="namespace", header="Namespace", sortable=True),
    DataTableColumn(key="label", header="Label", sortable=True),
    DataTableColumn(key="attr_count", header="Attributes", sortable=True),
    DataTableColumn(key="rel_count", header="Relationships", sortable=True),
]


def _build_mermaid_er_lines(
    catalog: list[dict[str, Any]],
    by_complexity: list[dict[str, Any]],
    mermaid_kinds: set[str],
    relationships_by_kind: dict[str, list[dict[str, Any]]],
) -> list[str]:
    """Build mermaid ER diagram lines from pre-fetched relationship data."""
    lines = ["erDiagram"]
    for entry in by_complexity[:_MERMAID_MAX_KINDS]:
        rels = relationships_by_kind.get(entry["kind"], [])
        for rel in rels:
            peer = rel["peer"]
            if peer not in mermaid_kinds:
                continue
            src_label = entry["kind"].split(entry["namespace"], 1)[-1] or entry["kind"]
            peer_ns = peer.split(
                next((e["namespace"] for e in catalog if e["kind"] == peer), ""),
                1,
            )
            peer_label = peer_ns[-1] if len(peer_ns) > 1 and peer_ns[-1] else peer
            lines.append(f"    {src_label} ||--o{{ {peer_label} : {rel['name']}")
    return lines


async def _build_mermaid_str(
    client: InfrahubClient,
    branch: str | None,
    catalog: list[dict[str, Any]],
    by_complexity: list[dict[str, Any]],
) -> str:
    """Fetch relationship details and build the mermaid ER string."""
    mermaid_kinds = {
        e["kind"] for e in by_complexity[:_MERMAID_MAX_KINDS]
    }
    rels_by_kind: dict[str, list[dict[str, Any]]] = {}
    for entry in by_complexity[:_MERMAID_MAX_KINDS]:
        if entry["rel_count"] > 0:
            try:
                detail = await fetch_schema_detail(
                    client, entry["kind"], branch,
                )
                rels_by_kind[entry["kind"]] = detail["relationships"]
            except Exception:  # noqa: BLE001
                logger.debug("Skipping mermaid for %s", entry["kind"])

    lines = _build_mermaid_er_lines(
        catalog, by_complexity, mermaid_kinds, rels_by_kind,
    )
    if len(lines) > 1:
        return "\n".join(lines)
    return "erDiagram\n    No_relationships { }"


def _compute_namespace_data(
    catalog: list[dict[str, Any]],
) -> tuple[Counter[str], list[dict[str, Any]]]:
    """Group catalog entries by namespace and return (counter, chart_data)."""
    ns_counter: Counter[str] = Counter()
    for entry in catalog:
        ns_counter[entry["namespace"]] += 1
    data = [
        {"name": ns, "value": count}
        for ns, count in ns_counter.most_common()
    ]
    return ns_counter, data


def _compute_complexity_ranking(
    catalog: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return user-defined kinds sorted by total fields descending."""
    user_kinds = [
        e for e in catalog
        if e["namespace"] not in _BUILTIN_NAMESPACES
    ]
    return sorted(
        user_kinds,
        key=lambda e: e["attr_count"] + e["rel_count"],
        reverse=True,
    )


async def _run_schema_report(
    store: ReportStore,
    client: InfrahubClient,
    report_id: str,
    branch: str | None,
) -> None:
    """Background task for the schema_report tool."""
    try:
        await store.update_progress(report_id, 0.3, "Fetching schema catalog...")
        catalog = await fetch_schema_catalog(client, branch)

        await store.update_progress(report_id, 0.5, "Analysing namespaces...")
        ns_counter, namespace_data = _compute_namespace_data(catalog)

        await store.update_progress(report_id, 0.7, "Computing complexity...")
        by_complexity = _compute_complexity_ranking(catalog)
        complexity_data = [
            {
                "label": e["label"],
                "attributes": e["attr_count"],
                "relationships": e["rel_count"],
            }
            for e in by_complexity[:_SCHEMA_COMPLEXITY_TOP_N]
        ]

        await store.update_progress(report_id, 0.9, "Building relationship map...")
        mermaid_str = await _build_mermaid_str(
            client, branch, catalog, by_complexity,
        )

        result = {
            "total_kinds": len(catalog),
            "namespace_count": len(ns_counter),
            "namespace_data": namespace_data,
            "complexity_data": complexity_data,
            "mermaid_str": mermaid_str,
            "catalog_rows": catalog,
        }
        await store.complete(report_id, result)
    except Exception as exc:
        logger.exception("schema_report failed")
        await store.fail(report_id, str(exc))


def _build_schema_namespaces_tab() -> None:
    """Build the Namespaces tab content for the schema_report."""
    with Column():
        with Grid(columns=2):
            Metric(label="Total Kinds", value=Rx("result.total_kinds"))
            Metric(label="Namespaces", value=Rx("result.namespace_count"))
        PieChart(data=Rx("result.namespace_data"), data_key="value", name_key="name")


def _build_schema_complexity_tab() -> None:
    """Build the Complexity tab content for the schema_report."""
    with Column():
        H3(content="Top Kinds by Field Count")
        BarChart(
            data=Rx("result.complexity_data"),
            x_axis="label",
            series=[
                ChartSeries(data_key="attributes"),
                ChartSeries(data_key="relationships"),
            ],
        )


@mcp.tool(app=True)
async def schema_report(ctx: Context, branch: str | None = None) -> PrefabApp:
    """Generate a visual map of the schema structure."""
    store = _get_store(ctx)
    client = _get_client(ctx)
    report = await store.create("Schema Report")

    _launch_background(_run_schema_report(store, client, report.id, branch))

    app = _build_polling_app("Schema Report", report.id)
    with app:
        with If(condition=Rx("status") == "running"):
            _add_loading_state()
        with Elif(condition=Rx("status") == "ready"):
            with Tabs(value="namespaces"):
                with Tab("Namespaces"):
                    _build_schema_namespaces_tab()
                with Tab("Complexity"):
                    _build_schema_complexity_tab()
                with Tab("Relationships"):
                    with Column():
                        H3(content="Entity Relationship Diagram")
                        Mermaid(chart=Rx("result.mermaid_str"))
                with Tab("Catalog"):
                    DataTable(
                        columns=_CATALOG_TABLE_COLUMNS,
                        rows=Rx("result.catalog_rows"),  # type: ignore[arg-type]
                        paginated=True,
                        page_size=10,
                    )
        with Else():
            _add_error_state()
    return app


# ---------------------------------------------------------------------------
# Report 3: data_report
# ---------------------------------------------------------------------------

# Static column definitions for data_report Details tab.
_DATA_DETAIL_TABLE_COLUMNS = [
    DataTableColumn(key="kind", header="Kind", sortable=True),
    DataTableColumn(key="label", header="Label", sortable=True),
    DataTableColumn(key="count", header="Count", sortable=True),
]


async def _run_data_report(
    store: ReportStore,
    client: InfrahubClient,
    report_id: str,
    branch: str | None,
) -> None:
    """Background task for the data_report tool."""
    try:
        await store.update_progress(report_id, 0.1, "Fetching schema catalog...")
        catalog = await fetch_schema_catalog(client, branch)
        kinds = [e["kind"] for e in catalog]

        async def _on_count_progress(done: int, total: int) -> None:
            progress = 0.2 + 0.6 * (done / total) if total > 0 else 0.8
            await store.update_progress(report_id, progress, f"Counting nodes... {done}/{total}")

        await store.update_progress(report_id, 0.2, "Counting nodes...")
        counts = await fetch_node_counts(client, kinds, branch, on_progress=_on_count_progress)

        await store.update_progress(report_id, 0.9, "Analysing data coverage...")
        total_nodes = sum(c["count"] for c in counts)
        populated = [c for c in counts if c["count"] > 0]
        empty = [c for c in counts if c["count"] == 0]

        # Coverage pie chart: populated vs empty kinds
        coverage_data = [
            {"name": "Populated", "value": len(populated)},
            {"name": "Empty", "value": len(empty)},
        ]

        # Distribution bar chart: top 20 kinds by count
        distribution_data = [{"label": c["label"], "count": c["count"]} for c in populated[:20]]

        result = {
            "total_nodes": total_nodes,
            "populated_count": len(populated),
            "empty_count": len(empty),
            "coverage_data": coverage_data,
            "distribution_data": distribution_data,
            "detail_rows": counts,
        }
        await store.complete(report_id, result)
    except Exception as exc:
        logger.exception("data_report failed")
        await store.fail(report_id, str(exc))


def _build_data_summary_tab() -> None:
    """Build the Summary tab content for the data_report."""
    with Column():
        with Grid(columns=3):
            Metric(label="Total Nodes", value=Rx("result.total_nodes"))
            Metric(label="Populated Kinds", value=Rx("result.populated_count"))
            Metric(label="Empty Kinds", value=Rx("result.empty_count"))
        H3(content="Schema Coverage")
        PieChart(data=Rx("result.coverage_data"), data_key="value", name_key="name")


def _build_data_distribution_tab() -> None:
    """Build the Distribution tab content for the data_report."""
    with Column():
        H3(content="Top Kinds by Node Count")
        BarChart(
            data=Rx("result.distribution_data"),
            x_axis="label",
            series=[ChartSeries(data_key="count")],
        )


@mcp.tool(app=True)
async def data_report(ctx: Context, branch: str | None = None) -> PrefabApp:
    """Generate an instance-wide data summary."""
    store = _get_store(ctx)
    client = _get_client(ctx)
    report = await store.create("Data Report")

    _launch_background(_run_data_report(store, client, report.id, branch))

    app = _build_polling_app("Data Report", report.id)
    with app:
        with If(condition=Rx("status") == "running"):
            _add_loading_state()
        with Elif(condition=Rx("status") == "ready"):
            with Tabs(value="summary"):
                with Tab("Summary"):
                    _build_data_summary_tab()
                with Tab("Distribution"):
                    _build_data_distribution_tab()
                with Tab("Details"):
                    DataTable(
                        columns=_DATA_DETAIL_TABLE_COLUMNS,
                        rows=Rx("result.detail_rows"),  # type: ignore[arg-type]
                        paginated=True,
                        page_size=10,
                    )
        with Else():
            _add_error_state()
    return app
