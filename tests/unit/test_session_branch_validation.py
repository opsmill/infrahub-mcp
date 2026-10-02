"""Tests for per-session branch resolution, recovery, and name conformance.

The active session branch is tracked per MCP session (keyed by the session
object) on ``AppContext``. The cached branch is validated against Infrahub
before reuse; if it was deleted (``BranchNotFoundError``) or merged / is being
removed (``status`` MERGED/DELETING — still present but read-only), the cache is
cleared and a fresh branch is provisioned without a server restart.
"""

from __future__ import annotations

import asyncio
import gc
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from infrahub_sdk.branch import BranchStatus
from infrahub_sdk.exceptions import BranchNotFoundError

from infrahub_mcp.config import ServerConfig
from infrahub_mcp.utils import (
    AppContext,
    branch_name_conforms,
    get_or_create_session_branch,
    get_session_branch,
)


def _make_ctx(app_ctx: AppContext) -> MagicMock:
    """Create a mock FastMCP Context with a stable per-session object."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    ctx.info = AsyncMock()
    ctx.warning = AsyncMock()
    ctx.debug = AsyncMock()
    ctx.error = AsyncMock()
    return ctx


def _branch(status: BranchStatus) -> MagicMock:
    branch = MagicMock()
    branch.status = status
    return branch


class TestGetOrCreateSessionBranch:
    async def test_returns_cached_branch_when_it_still_exists(self) -> None:
        """A still-writable cached branch is reused — no re-create."""
        config = ServerConfig(auth_mode="none")
        app_ctx = AppContext(client=MagicMock(), config=config)
        ctx = _make_ctx(app_ctx)
        app_ctx._session_branches[ctx.request_context.session] = "mcp/session-existing"  # noqa: SLF001

        client = MagicMock()
        client.branch.get = AsyncMock(return_value=_branch(BranchStatus.OPEN))
        client.branch.create = AsyncMock()

        with patch("infrahub_mcp.utils.get_client", return_value=client):
            result = await get_or_create_session_branch(ctx)

        assert result == "mcp/session-existing"
        assert get_session_branch(ctx) == "mcp/session-existing"
        client.branch.create.assert_not_called()
        client.branch.get.assert_called_once_with(branch_name="mcp/session-existing")

    @pytest.mark.parametrize("status", [BranchStatus.OPEN, BranchStatus.NEED_REBASE])
    async def test_reuses_writable_statuses(self, status: BranchStatus) -> None:
        """OPEN and NEED_REBASE branches are writable and reused."""
        config = ServerConfig(auth_mode="none")
        app_ctx = AppContext(client=MagicMock(), config=config)
        ctx = _make_ctx(app_ctx)
        app_ctx._session_branches[ctx.request_context.session] = "mcp/session-reuse"  # noqa: SLF001

        client = MagicMock()
        client.branch.get = AsyncMock(return_value=_branch(status))
        client.branch.create = AsyncMock()

        with patch("infrahub_mcp.utils.get_client", return_value=client):
            result = await get_or_create_session_branch(ctx)

        assert result == "mcp/session-reuse"
        client.branch.create.assert_not_called()

    async def test_recreates_when_cached_branch_was_deleted(self) -> None:
        """A deleted cached branch (BranchNotFoundError) triggers creation of a new one."""
        config = ServerConfig(auth_mode="none", branch_pattern="mcp/session-{date}-{hex}")
        app_ctx = AppContext(client=MagicMock(), config=config)
        ctx = _make_ctx(app_ctx)
        app_ctx._session_branches[ctx.request_context.session] = "mcp/session-stale"  # noqa: SLF001

        client = MagicMock()
        client.branch.get = AsyncMock(side_effect=BranchNotFoundError(identifier="mcp/session-stale"))
        client.branch.create = AsyncMock()

        with patch("infrahub_mcp.utils.get_client", return_value=client):
            result = await get_or_create_session_branch(ctx)

        assert result != "mcp/session-stale"
        assert result.startswith("mcp/session-")
        assert get_session_branch(ctx) == result
        client.branch.create.assert_called_once()
        ctx.warning.assert_awaited()

    @pytest.mark.parametrize("status", [BranchStatus.MERGED, BranchStatus.DELETING])
    async def test_recovers_when_cached_branch_unwritable(self, status: BranchStatus) -> None:
        """A merged/deleting cached branch (present but read-only) is recovered onto a new branch."""
        config = ServerConfig(auth_mode="none", branch_pattern="mcp/session-{date}-{hex}")
        app_ctx = AppContext(client=MagicMock(), config=config)
        ctx = _make_ctx(app_ctx)
        app_ctx._session_branches[ctx.request_context.session] = "mcp/session-merged"  # noqa: SLF001

        client = MagicMock()
        client.branch.get = AsyncMock(return_value=_branch(status))
        client.branch.create = AsyncMock()

        with patch("infrahub_mcp.utils.get_client", return_value=client):
            result = await get_or_create_session_branch(ctx)

        assert result != "mcp/session-merged"
        assert result.startswith("mcp/session-")
        assert get_session_branch(ctx) == result
        client.branch.create.assert_called_once()
        ctx.warning.assert_awaited()  # SC-005: old + new named

    async def test_creates_when_no_cached_branch(self) -> None:
        """First write of a session creates a new branch — no validation lookup."""
        config = ServerConfig(auth_mode="none", branch_pattern="mcp/session-{date}-{hex}")
        app_ctx = AppContext(client=MagicMock(), config=config)
        ctx = _make_ctx(app_ctx)

        client = MagicMock()
        client.branch.get = AsyncMock()
        client.branch.create = AsyncMock()

        with patch("infrahub_mcp.utils.get_client", return_value=client):
            result = await get_or_create_session_branch(ctx)

        assert result.startswith("mcp/session-")
        assert get_session_branch(ctx) == result
        client.branch.create.assert_called_once()
        client.branch.get.assert_not_called()

    async def test_recovery_isolated_per_session(self) -> None:
        """Recovery in one session does not touch another session's branch (FR-010 / SC-006)."""
        config = ServerConfig(auth_mode="none", branch_pattern="mcp/session-{date}-{hex}")
        app_ctx = AppContext(client=MagicMock(), config=config)
        ctx_a = _make_ctx(app_ctx)
        ctx_b = _make_ctx(app_ctx)
        app_ctx._session_branches[ctx_a.request_context.session] = "mcp/session-A"  # noqa: SLF001
        app_ctx._session_branches[ctx_b.request_context.session] = "mcp/session-B"  # noqa: SLF001

        client = MagicMock()
        client.branch.get = AsyncMock(return_value=_branch(BranchStatus.MERGED))
        client.branch.create = AsyncMock()

        with patch("infrahub_mcp.utils.get_client", return_value=client):
            await get_or_create_session_branch(ctx_a)

        # Session B is untouched by Session A's recovery.
        assert get_session_branch(ctx_b) == "mcp/session-B"
        assert get_session_branch(ctx_a) != "mcp/session-A"

    async def test_concurrent_first_writes_converge_on_one_branch(self) -> None:
        """Concurrent writes in one session create exactly one branch (FR-008)."""
        config = ServerConfig(auth_mode="none", branch_pattern="mcp/session-{date}-{hex}")
        app_ctx = AppContext(client=MagicMock(), config=config)
        ctx = _make_ctx(app_ctx)

        client = MagicMock()
        client.branch.get = AsyncMock(return_value=_branch(BranchStatus.OPEN))
        client.branch.create = AsyncMock()

        with patch("infrahub_mcp.utils.get_client", return_value=client):
            first, second = await asyncio.gather(
                get_or_create_session_branch(ctx),
                get_or_create_session_branch(ctx),
            )

        assert first == second
        client.branch.create.assert_called_once()


class TestSessionStateLifecycle:
    def test_session_entry_released_when_session_collected(self) -> None:
        """Per-session entries are weakly held and released at session end (no leak — FR-010)."""
        app_ctx = AppContext(client=MagicMock(), config=ServerConfig(auth_mode="none"))

        class _Session:
            """Stand-in for a per-session object (weak-referenceable)."""

        sess = _Session()
        app_ctx._session_branches[sess] = "mcp/session-x"  # noqa: SLF001
        assert len(app_ctx._session_branches) == 1  # noqa: SLF001

        del sess
        gc.collect()

        assert len(app_ctx._session_branches) == 0  # noqa: SLF001


class TestBranchNameConforms:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("mcp/session-20260604-ab12cd34", True),
            ("mcp/session-2026-ab12cd34", False),  # {date} wrong length
            ("mcp/session-20260604-ZZZZ", False),  # {hex} not 8 lowercase hex
            ("totally-random-name", False),  # no match
            ("mcp/session-20260604-ab12cd34/extra", False),  # trailing extra
        ],
    )
    def test_default_pattern(self, name: str, expected: bool) -> None:
        assert branch_name_conforms(name, "mcp/session-{date}-{hex}") is expected

    def test_fixed_pattern_requires_exact_match(self) -> None:
        assert branch_name_conforms("mybranch", "mybranch") is True
        assert branch_name_conforms("other", "mybranch") is False

    def test_user_placeholder_respects_separators(self) -> None:
        assert branch_name_conforms("mcp/alice/work", "mcp/{user}/work") is True
        assert branch_name_conforms("mcp/alice/nope", "mcp/{user}/work") is False
        # {user} must not span literal '/' separators (would otherwise over-match).
        assert branch_name_conforms("mcp/a/b/work", "mcp/{user}/work") is False

    def test_rejects_disallowed_characters(self) -> None:
        assert branch_name_conforms("mcp/session-20260604-ab12cd34 ", "mcp/session-{date}-{hex}") is False
