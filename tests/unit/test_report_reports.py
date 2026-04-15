"""Tests for the report tool endpoints and their background tasks."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import Context
from prefab_ui.app import PrefabApp

from infrahub_mcp.reports.reports import (
    _run_data_report,
    _run_kind_report,
    _run_schema_report,
    data_report,
    get_report_state,
    kind_report,
    schema_report,
)
from infrahub_mcp.reports.store import ReportStatus, ReportStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ctx(store: ReportStore | None = None, client: AsyncMock | None = None) -> MagicMock:
    """Create a mock MCP Context with AppContext."""
    ctx = MagicMock(spec=Context)
    app_ctx = MagicMock()
    app_ctx.client = client or AsyncMock()
    app_ctx.report_store = store or ReportStore()
    ctx.request_context.lifespan_context = app_ctx
    return ctx


# Shared fake data used by multiple tests
_FAKE_SCHEMA_DETAIL = {
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

_FAKE_CATALOG = [
    {"kind": "InfraDevice", "namespace": "Infra", "label": "Device", "attr_count": 5, "rel_count": 3},
    {"kind": "InfraPlatform", "namespace": "Infra", "label": "Platform", "attr_count": 2, "rel_count": 1},
    {"kind": "CoreAccount", "namespace": "Core", "label": "Account", "attr_count": 4, "rel_count": 2},
]

_FAKE_FIELD_DISTRIBUTIONS = [
    {"field": "status", "distribution": [{"value": "active", "count": 2}, {"value": "decommissioned", "count": 1}]},
]

_FAKE_REL_DISTRIBUTIONS = [
    {"field": "platform", "distribution": [{"value": "Juniper", "count": 2}, {"value": "Cisco", "count": 1}]},
]

_FAKE_COUNTS = [
    {"kind": "InfraDevice", "label": "Device", "count": 30},
    {"kind": "InfraPlatform", "label": "Platform", "count": 5},
    {"kind": "CoreAccount", "label": "Account", "count": 0},
]


# ---------------------------------------------------------------------------
# Tool return type tests
# ---------------------------------------------------------------------------


class TestKindReportTool:
    @patch("infrahub_mcp.reports.reports._launch_background")
    async def test_returns_prefab_app(self, mock_launch: MagicMock) -> None:
        store = ReportStore()
        ctx = _make_ctx(store=store)
        result = await kind_report(kind="InfraDevice", ctx=ctx)
        assert isinstance(result, PrefabApp)

    @patch("infrahub_mcp.reports.reports._launch_background")
    async def test_has_correct_title(self, mock_launch: MagicMock) -> None:
        store = ReportStore()
        ctx = _make_ctx(store=store)
        result = await kind_report(kind="InfraDevice", ctx=ctx)
        assert result.title == "Kind Report: InfraDevice"  # type: ignore[attr-defined]

    @patch("infrahub_mcp.reports.reports._launch_background")
    async def test_launches_background_task(self, mock_launch: MagicMock) -> None:
        store = ReportStore()
        ctx = _make_ctx(store=store)
        await kind_report(kind="InfraDevice", ctx=ctx)
        mock_launch.assert_called_once()

    @patch("infrahub_mcp.reports.reports._launch_background")
    async def test_creates_report_in_store(self, mock_launch: MagicMock) -> None:
        store = ReportStore()
        ctx = _make_ctx(store=store)
        await kind_report(kind="InfraDevice", ctx=ctx)
        reports = await store.list_reports()
        assert len(reports) == 1
        assert reports[0].name == "Kind Report: InfraDevice"


class TestSchemaReportTool:
    @patch("infrahub_mcp.reports.reports._launch_background")
    async def test_returns_prefab_app(self, mock_launch: MagicMock) -> None:
        store = ReportStore()
        ctx = _make_ctx(store=store)
        result = await schema_report(ctx=ctx)
        assert isinstance(result, PrefabApp)

    @patch("infrahub_mcp.reports.reports._launch_background")
    async def test_has_correct_title(self, mock_launch: MagicMock) -> None:
        store = ReportStore()
        ctx = _make_ctx(store=store)
        result = await schema_report(ctx=ctx)
        assert result.title == "Schema Report"  # type: ignore[attr-defined]

    @patch("infrahub_mcp.reports.reports._launch_background")
    async def test_launches_background_task(self, mock_launch: MagicMock) -> None:
        store = ReportStore()
        ctx = _make_ctx(store=store)
        await schema_report(ctx=ctx)
        mock_launch.assert_called_once()


class TestDataReportTool:
    @patch("infrahub_mcp.reports.reports._launch_background")
    async def test_returns_prefab_app(self, mock_launch: MagicMock) -> None:
        store = ReportStore()
        ctx = _make_ctx(store=store)
        result = await data_report(ctx=ctx)
        assert isinstance(result, PrefabApp)

    @patch("infrahub_mcp.reports.reports._launch_background")
    async def test_has_correct_title(self, mock_launch: MagicMock) -> None:
        store = ReportStore()
        ctx = _make_ctx(store=store)
        result = await data_report(ctx=ctx)
        assert result.title == "Data Report"  # type: ignore[attr-defined]

    @patch("infrahub_mcp.reports.reports._launch_background")
    async def test_launches_background_task(self, mock_launch: MagicMock) -> None:
        store = ReportStore()
        ctx = _make_ctx(store=store)
        await data_report(ctx=ctx)
        mock_launch.assert_called_once()


# ---------------------------------------------------------------------------
# get_report_state tests
# ---------------------------------------------------------------------------


class TestGetReportState:
    async def test_returns_status_for_existing_report(self) -> None:
        store = ReportStore()
        report = await store.create("Test Report")
        await store.update_progress(report.id, 0.5, "Half done")
        ctx = _make_ctx(store=store)
        result = await get_report_state(report_id=report.id, ctx=ctx)
        assert result["status"] == "running"
        assert result["progress"] == pytest.approx(0.5)
        assert result["status_message"] == "Half done"
        assert result["error"] is None

    async def test_returns_error_for_nonexistent_report(self) -> None:
        store = ReportStore()
        ctx = _make_ctx(store=store)
        result = await get_report_state(report_id="nonexistent", ctx=ctx)
        assert result["status"] == "error"
        assert result["error"] == "Report not found"

    async def test_returns_ready_status_with_result(self) -> None:
        store = ReportStore()
        report = await store.create("Test Report")
        await store.complete(report.id, {"data": "test"})
        ctx = _make_ctx(store=store)
        result = await get_report_state(report_id=report.id, ctx=ctx)
        assert result["status"] == "ready"
        assert result["result"] == {"data": "test"}
        assert result["progress"] == pytest.approx(1.0)

    async def test_returns_error_status_with_message(self) -> None:
        store = ReportStore()
        report = await store.create("Test Report")
        await store.fail(report.id, "Something broke")
        ctx = _make_ctx(store=store)
        result = await get_report_state(report_id=report.id, ctx=ctx)
        assert result["status"] == "error"
        assert result["error"] == "Something broke"


# ---------------------------------------------------------------------------
# Background task: _run_kind_report
# ---------------------------------------------------------------------------


class TestRunKindReport:
    @patch("infrahub_mcp.reports.reports.compute_relationship_distributions", return_value=_FAKE_REL_DISTRIBUTIONS)
    @patch("infrahub_mcp.reports.reports.compute_field_distributions", return_value=_FAKE_FIELD_DISTRIBUTIONS)
    @patch("infrahub_mcp.reports.reports.fetch_nodes_for_kind", return_value=(_FAKE_NODES, _FAKE_COLUMNS))
    @patch("infrahub_mcp.reports.reports.fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    async def test_completes_with_result(
        self,
        mock_schema: MagicMock,
        mock_nodes: MagicMock,
        mock_field_dist: MagicMock,
        mock_rel_dist: MagicMock,
    ) -> None:
        store = ReportStore()
        client = AsyncMock()
        report = await store.create("Kind Report: InfraDevice")

        await _run_kind_report(store, client, report.id, "InfraDevice", None)

        updated = await store.get(report.id)
        assert updated is not None
        assert updated.status == ReportStatus.ready
        assert updated.result is not None
        assert updated.result["node_count"] == 3
        assert updated.result["attr_count"] == 2
        assert updated.result["rel_count"] == 1
        assert len(updated.result["field_charts"]) == 1
        assert len(updated.result["rel_charts"]) == 1

    @patch("infrahub_mcp.reports.reports.compute_relationship_distributions", return_value=_FAKE_REL_DISTRIBUTIONS)
    @patch("infrahub_mcp.reports.reports.compute_field_distributions", return_value=_FAKE_FIELD_DISTRIBUTIONS)
    @patch("infrahub_mcp.reports.reports.fetch_nodes_for_kind", return_value=(_FAKE_NODES, _FAKE_COLUMNS))
    @patch("infrahub_mcp.reports.reports.fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    async def test_result_has_correct_chart_shape(
        self,
        mock_schema: MagicMock,
        mock_nodes: MagicMock,
        mock_field_dist: MagicMock,
        mock_rel_dist: MagicMock,
    ) -> None:
        store = ReportStore()
        client = AsyncMock()
        report = await store.create("Kind Report: InfraDevice")

        await _run_kind_report(store, client, report.id, "InfraDevice", None)

        updated = await store.get(report.id)
        assert updated is not None
        assert updated.result is not None
        field_chart = updated.result["field_charts"][0]
        assert field_chart["field"] == "status"
        assert field_chart["data"][0]["name"] == "active"
        assert field_chart["data"][0]["value"] == 2

        rel_chart = updated.result["rel_charts"][0]
        assert rel_chart["field"] == "platform"
        assert rel_chart["data"][0]["label"] == "Juniper"
        assert rel_chart["data"][0]["count"] == 2

    @patch("infrahub_mcp.reports.reports.fetch_schema_detail", side_effect=Exception("Schema fetch failed"))
    async def test_fails_on_fetcher_error(self, mock_schema: MagicMock) -> None:
        store = ReportStore()
        client = AsyncMock()
        report = await store.create("Kind Report: BadKind")

        await _run_kind_report(store, client, report.id, "BadKind", None)

        updated = await store.get(report.id)
        assert updated is not None
        assert updated.status == ReportStatus.error
        assert updated.error == "Schema fetch failed"


# ---------------------------------------------------------------------------
# Background task: _run_schema_report
# ---------------------------------------------------------------------------


class TestRunSchemaReport:
    @patch("infrahub_mcp.reports.reports.fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    @patch("infrahub_mcp.reports.reports.fetch_schema_catalog", return_value=_FAKE_CATALOG)
    async def test_completes_with_result(
        self,
        mock_catalog: MagicMock,
        mock_detail: MagicMock,
    ) -> None:
        store = ReportStore()
        client = AsyncMock()
        report = await store.create("Schema Report")

        await _run_schema_report(store, client, report.id, None)

        updated = await store.get(report.id)
        assert updated is not None
        assert updated.status == ReportStatus.ready
        assert updated.result is not None
        assert updated.result["total_kinds"] == 3
        assert updated.result["namespace_count"] == 2  # Infra + Core

    @patch("infrahub_mcp.reports.reports.fetch_schema_detail", return_value=_FAKE_SCHEMA_DETAIL)
    @patch("infrahub_mcp.reports.reports.fetch_schema_catalog", return_value=_FAKE_CATALOG)
    async def test_excludes_builtin_from_complexity(
        self,
        mock_catalog: MagicMock,
        mock_detail: MagicMock,
    ) -> None:
        store = ReportStore()
        client = AsyncMock()
        report = await store.create("Schema Report")

        await _run_schema_report(store, client, report.id, None)

        updated = await store.get(report.id)
        assert updated is not None
        assert updated.result is not None
        complexity_labels = [c["label"] for c in updated.result["complexity_data"]]
        assert "Account" not in complexity_labels  # Core namespace excluded
        assert "Device" in complexity_labels

    @patch("infrahub_mcp.reports.reports.fetch_schema_catalog", side_effect=Exception("Catalog failed"))
    async def test_fails_on_fetcher_error(self, mock_catalog: MagicMock) -> None:
        store = ReportStore()
        client = AsyncMock()
        report = await store.create("Schema Report")

        await _run_schema_report(store, client, report.id, None)

        updated = await store.get(report.id)
        assert updated is not None
        assert updated.status == ReportStatus.error
        assert updated.error == "Catalog failed"


# ---------------------------------------------------------------------------
# Background task: _run_data_report
# ---------------------------------------------------------------------------


class TestRunDataReport:
    @patch("infrahub_mcp.reports.reports.fetch_node_counts", return_value=_FAKE_COUNTS)
    @patch("infrahub_mcp.reports.reports.fetch_schema_catalog", return_value=_FAKE_CATALOG)
    async def test_completes_with_result(
        self,
        mock_catalog: MagicMock,
        mock_counts: MagicMock,
    ) -> None:
        store = ReportStore()
        client = AsyncMock()
        report = await store.create("Data Report")

        await _run_data_report(store, client, report.id, None)

        updated = await store.get(report.id)
        assert updated is not None
        assert updated.status == ReportStatus.ready
        assert updated.result is not None
        assert updated.result["total_nodes"] == 35
        assert updated.result["populated_count"] == 2
        assert updated.result["empty_count"] == 1

    @patch("infrahub_mcp.reports.reports.fetch_node_counts", return_value=_FAKE_COUNTS)
    @patch("infrahub_mcp.reports.reports.fetch_schema_catalog", return_value=_FAKE_CATALOG)
    async def test_coverage_data_shape(
        self,
        mock_catalog: MagicMock,
        mock_counts: MagicMock,
    ) -> None:
        store = ReportStore()
        client = AsyncMock()
        report = await store.create("Data Report")

        await _run_data_report(store, client, report.id, None)

        updated = await store.get(report.id)
        assert updated is not None
        assert updated.result is not None
        coverage = updated.result["coverage_data"]
        assert len(coverage) == 2
        populated = next(c for c in coverage if c["name"] == "Populated")
        assert populated["value"] == 2

    @patch("infrahub_mcp.reports.reports.fetch_node_counts", return_value=_FAKE_COUNTS)
    @patch("infrahub_mcp.reports.reports.fetch_schema_catalog", return_value=_FAKE_CATALOG)
    async def test_progress_callback_called(
        self,
        mock_catalog: MagicMock,
        mock_counts: MagicMock,
    ) -> None:
        store = ReportStore()
        client = AsyncMock()
        report = await store.create("Data Report")

        await _run_data_report(store, client, report.id, None)

        # Verify that update_progress was called (the on_progress callback
        # is passed to fetch_node_counts). We can verify by checking the
        # on_progress kwarg was passed.
        mock_counts.assert_called_once()
        call_kwargs = mock_counts.call_args
        assert call_kwargs is not None
        # on_progress should be passed as a keyword argument
        assert "on_progress" in call_kwargs.kwargs or (len(call_kwargs.args) >= 4)

    @patch("infrahub_mcp.reports.reports.fetch_schema_catalog", side_effect=Exception("Connection refused"))
    async def test_fails_on_fetcher_error(self, mock_catalog: MagicMock) -> None:
        store = ReportStore()
        client = AsyncMock()
        report = await store.create("Data Report")

        await _run_data_report(store, client, report.id, None)

        updated = await store.get(report.id)
        assert updated is not None
        assert updated.status == ReportStatus.error
        assert updated.error == "Connection refused"

    @patch("infrahub_mcp.reports.reports.fetch_node_counts", return_value=_FAKE_COUNTS)
    @patch("infrahub_mcp.reports.reports.fetch_schema_catalog", return_value=_FAKE_CATALOG)
    async def test_distribution_data_limited_to_top_20(
        self,
        mock_catalog: MagicMock,
        mock_counts: MagicMock,
    ) -> None:
        store = ReportStore()
        client = AsyncMock()
        report = await store.create("Data Report")

        await _run_data_report(store, client, report.id, None)

        updated = await store.get(report.id)
        assert updated is not None
        assert updated.result is not None
        assert len(updated.result["distribution_data"]) <= 20
