"""Session-scoped store for tracking report generation status."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class ReportStatus(StrEnum):
    """Lifecycle states for a report."""

    pending = "pending"
    running = "running"
    ready = "ready"
    error = "error"


@dataclass
class Report:
    """A single analytics report tracked by the store."""

    id: str
    name: str
    status: ReportStatus
    progress: float
    status_message: str
    result: dict[str, Any] | None
    error: str | None
    created_at: datetime


class ReportStore:
    """In-memory, session-scoped store for report state.

    All public methods are async and protected by an asyncio.Lock so that
    concurrent coroutines cannot corrupt state.
    """

    def __init__(self) -> None:
        self._reports: dict[str, Report] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    async def create(self, name: str) -> Report:
        """Create a new report with pending status.

        Args:
            name: Human-readable label for the report (e.g. "Kind Report: InfraDevice").

        Returns:
            The newly created Report in ``pending`` state.
        """
        report = Report(
            id=uuid.uuid4().hex,
            name=name,
            status=ReportStatus.pending,
            progress=0.0,
            status_message="",
            result=None,
            error=None,
            created_at=datetime.now(tz=UTC),
        )
        async with self._lock:
            self._reports[report.id] = report
        return report

    async def get(self, report_id: str) -> Report | None:
        """Return a report by ID, or None if not found.

        Args:
            report_id: The UUID hex string assigned at creation time.

        Returns:
            The matching Report, or None.
        """
        async with self._lock:
            return self._reports.get(report_id)

    async def update_progress(self, report_id: str, progress: float, message: str) -> None:
        """Update progress and status message; set status to running.

        Args:
            report_id: ID of the report to update.
            progress: Completion fraction in the range 0.0-1.0.
            message: Human-readable progress description (e.g. "Fetching counts… 12/45").
        """
        async with self._lock:
            report = self._reports.get(report_id)
            if report is None:
                return
            report.progress = progress
            report.status_message = message
            report.status = ReportStatus.running

    async def complete(self, report_id: str, result: dict[str, Any]) -> None:
        """Mark the report as ready and attach the result payload.

        Args:
            report_id: ID of the report to finalise.
            result: Fetched data ready for chart builders (dicts/lists, not rendered UI).
        """
        async with self._lock:
            report = self._reports.get(report_id)
            if report is None:
                return
            report.result = result
            report.status = ReportStatus.ready
            report.progress = 1.0

    async def fail(self, report_id: str, error: str) -> None:
        """Mark the report as errored and record the error message.

        Args:
            report_id: ID of the report that failed.
            error: Description of what went wrong.
        """
        async with self._lock:
            report = self._reports.get(report_id)
            if report is None:
                return
            report.error = error
            report.status = ReportStatus.error

    async def list_reports(self) -> list[Report]:
        """Return all reports ordered newest-first by creation time.

        Returns:
            Sorted list of all tracked reports.
        """
        async with self._lock:
            return sorted(self._reports.values(), key=lambda r: r.created_at, reverse=True)
