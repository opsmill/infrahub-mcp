"""Tests for the session-scoped ReportStore."""

from __future__ import annotations

import asyncio

import pytest

from infrahub_mcp.reports.store import Report, ReportStatus, ReportStore


class TestReportStoreCreate:
    async def test_create_returns_report_with_pending_status(self) -> None:
        store = ReportStore()
        report = await store.create("Kind Report: InfraDevice")
        assert isinstance(report, Report)
        assert report.status == ReportStatus.pending

    async def test_create_initialises_progress_to_zero(self) -> None:
        store = ReportStore()
        report = await store.create("My Report")
        assert report.progress == 0.0

    async def test_create_initialises_status_message_to_empty_string(self) -> None:
        store = ReportStore()
        report = await store.create("My Report")
        assert report.status_message == ""

    async def test_create_result_and_error_are_none(self) -> None:
        store = ReportStore()
        report = await store.create("My Report")
        assert report.result is None
        assert report.error is None

    async def test_create_assigns_nonempty_id(self) -> None:
        store = ReportStore()
        report = await store.create("My Report")
        assert report.id
        assert len(report.id) == 32  # uuid4().hex is 32 hex chars

    async def test_create_stores_name(self) -> None:
        store = ReportStore()
        report = await store.create("Kind Report: InfraDevice")
        assert report.name == "Kind Report: InfraDevice"

    async def test_create_sets_created_at(self) -> None:
        from datetime import UTC, datetime

        store = ReportStore()
        before = datetime.now(tz=UTC)
        report = await store.create("My Report")
        after = datetime.now(tz=UTC)
        assert before <= report.created_at <= after


class TestReportStoreGet:
    async def test_get_returns_report_by_id(self) -> None:
        store = ReportStore()
        created = await store.create("My Report")
        fetched = await store.get(created.id)
        assert fetched is created

    async def test_get_returns_none_for_unknown_id(self) -> None:
        store = ReportStore()
        result = await store.get("nonexistent-id")
        assert result is None

    async def test_get_returns_none_on_empty_store(self) -> None:
        store = ReportStore()
        result = await store.get("anything")
        assert result is None


class TestReportStoreUpdateProgress:
    async def test_update_progress_sets_progress_float(self) -> None:
        store = ReportStore()
        report = await store.create("My Report")
        await store.update_progress(report.id, 0.5, "Halfway")
        updated = await store.get(report.id)
        assert updated is not None
        assert updated.progress == pytest.approx(0.5)

    async def test_update_progress_sets_message(self) -> None:
        store = ReportStore()
        report = await store.create("My Report")
        await store.update_progress(report.id, 0.3, "Fetching counts... 12/45")
        updated = await store.get(report.id)
        assert updated is not None
        assert updated.status_message == "Fetching counts... 12/45"

    async def test_update_progress_sets_status_to_running(self) -> None:
        store = ReportStore()
        report = await store.create("My Report")
        assert report.status == ReportStatus.pending
        await store.update_progress(report.id, 0.1, "Starting")
        updated = await store.get(report.id)
        assert updated is not None
        assert updated.status == ReportStatus.running

    async def test_update_progress_on_unknown_id_is_noop(self) -> None:
        store = ReportStore()
        # Should not raise
        await store.update_progress("nonexistent", 0.5, "msg")


class TestReportStoreComplete:
    async def test_complete_sets_status_to_ready(self) -> None:
        store = ReportStore()
        report = await store.create("My Report")
        await store.complete(report.id, {"counts": [1, 2, 3]})
        updated = await store.get(report.id)
        assert updated is not None
        assert updated.status == ReportStatus.ready

    async def test_complete_stores_result_dict(self) -> None:
        store = ReportStore()
        report = await store.create("My Report")
        payload: dict[str, object] = {"counts": [1, 2, 3], "total": 6}
        await store.complete(report.id, payload)
        updated = await store.get(report.id)
        assert updated is not None
        assert updated.result == payload

    async def test_complete_sets_progress_to_one(self) -> None:
        store = ReportStore()
        report = await store.create("My Report")
        await store.complete(report.id, {})
        updated = await store.get(report.id)
        assert updated is not None
        assert updated.progress == pytest.approx(1.0)

    async def test_complete_on_unknown_id_is_noop(self) -> None:
        store = ReportStore()
        # Should not raise
        await store.complete("nonexistent", {"data": []})


class TestReportStoreFail:
    async def test_fail_sets_status_to_error(self) -> None:
        store = ReportStore()
        report = await store.create("My Report")
        await store.fail(report.id, "Connection refused")
        updated = await store.get(report.id)
        assert updated is not None
        assert updated.status == ReportStatus.error

    async def test_fail_stores_error_string(self) -> None:
        store = ReportStore()
        report = await store.create("My Report")
        await store.fail(report.id, "Connection refused")
        updated = await store.get(report.id)
        assert updated is not None
        assert updated.error == "Connection refused"

    async def test_fail_on_unknown_id_is_noop(self) -> None:
        store = ReportStore()
        # Should not raise
        await store.fail("nonexistent", "some error")


class TestReportStoreListReports:
    async def test_list_reports_returns_newest_first(self) -> None:
        store = ReportStore()
        first = await store.create("First")
        second = await store.create("Second")
        third = await store.create("Third")
        reports = await store.list_reports()
        assert len(reports) == 3
        # Newest is last created; creation order may have same timestamp so check IDs are all present
        ids = [r.id for r in reports]
        assert third.id in ids
        assert second.id in ids
        assert first.id in ids
        # Newest (latest created_at) should be first in the list
        assert reports[0].created_at >= reports[1].created_at >= reports[2].created_at

    async def test_list_reports_empty_store(self) -> None:
        store = ReportStore()
        reports = await store.list_reports()
        assert reports == []

    async def test_list_reports_single_item(self) -> None:
        store = ReportStore()
        report = await store.create("Only Report")
        reports = await store.list_reports()
        assert len(reports) == 1
        assert reports[0] is report


class TestReportStoreConcurrency:
    async def test_concurrent_updates_do_not_corrupt_state(self) -> None:
        store = ReportStore()

        # Create two independent reports
        report_a = await store.create("Report A")
        report_b = await store.create("Report B")

        async def update_a() -> None:
            for i in range(1, 6):
                await store.update_progress(report_a.id, i / 10, f"A step {i}")

        async def update_b() -> None:
            for i in range(1, 6):
                await store.update_progress(report_b.id, i / 10, f"B step {i}")

        await asyncio.gather(update_a(), update_b())

        final_a = await store.get(report_a.id)
        final_b = await store.get(report_b.id)

        assert final_a is not None
        assert final_b is not None
        assert final_a.status == ReportStatus.running
        assert final_b.status == ReportStatus.running
        assert final_a.progress == pytest.approx(0.5)
        assert final_b.progress == pytest.approx(0.5)

    async def test_concurrent_creates_produce_unique_ids(self) -> None:
        store = ReportStore()

        reports = await asyncio.gather(*[store.create(f"Report {i}") for i in range(20)])
        ids = [r.id for r in reports]

        assert len(ids) == len(set(ids)), "All report IDs must be unique"
