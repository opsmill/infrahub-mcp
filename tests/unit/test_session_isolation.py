"""Tests for per-MCP-session isolation of the session branch.

Regression coverage for the bug where ``session_branch`` was cached on the
process-wide ``AppContext``, causing every MCP session served by the same
server process to reuse the same branch — both stale-cache symptoms (the
underlying branch may have been deleted) and a credential leak in
passthrough auth modes (User A's branch becomes User B's).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from infrahub_mcp.config import ServerConfig
from infrahub_mcp.utils import AppContext, get_or_create_session_branch


class _SessionState:
    """In-memory stand-in for FastMCP's per-session state store."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def get_state(self, key: str) -> Any:
        return self._data.get(key)

    async def set_state(self, key: str, value: Any, **_: Any) -> None:
        self._data[key] = value


def _make_ctx(app_ctx: AppContext, client: MagicMock) -> MagicMock:
    """Create a mock FastMCP Context with isolated per-session state."""
    state = _SessionState()
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    ctx.info = AsyncMock()
    ctx.warning = AsyncMock()
    ctx.debug = AsyncMock()
    ctx.get_state = state.get_state
    ctx.set_state = state.set_state
    # get_client(ctx) returns this client — patch into utils via monkeypatch
    ctx._test_client = client  # noqa: SLF001
    return ctx


class TestSessionBranchIsolation:
    async def test_two_sessions_get_independent_branches(self, monkeypatch: Any) -> None:
        """Two MCP sessions sharing one server process must not share a branch."""
        config = ServerConfig(auth_mode="none", branch_pattern="mcp/session-{hex}")
        app_ctx = AppContext(client=MagicMock(), config=config)

        client_a = MagicMock()
        client_a.branch.create = AsyncMock()
        client_b = MagicMock()
        client_b.branch.create = AsyncMock()

        ctx_a = _make_ctx(app_ctx, client_a)
        ctx_b = _make_ctx(app_ctx, client_b)

        def fake_get_client(ctx: Any) -> Any:
            return ctx._test_client  # noqa: SLF001

        monkeypatch.setattr("infrahub_mcp.utils.get_client", fake_get_client)

        branch_a = await get_or_create_session_branch(ctx_a)
        branch_b = await get_or_create_session_branch(ctx_b)

        assert branch_a != branch_b
        assert branch_a.startswith("mcp/session-")
        assert branch_b.startswith("mcp/session-")
        client_a.branch.create.assert_called_once()
        client_b.branch.create.assert_called_once()

    async def test_same_session_reuses_cached_branch(self, monkeypatch: Any) -> None:
        """Two writes within the same MCP session reuse the same branch."""
        config = ServerConfig(auth_mode="none", branch_pattern="mcp/session-{hex}")
        app_ctx = AppContext(client=MagicMock(), config=config)

        client = MagicMock()
        client.branch.create = AsyncMock()
        ctx = _make_ctx(app_ctx, client)

        def fake_get_client(_: Any) -> Any:
            return client

        monkeypatch.setattr("infrahub_mcp.utils.get_client", fake_get_client)

        first = await get_or_create_session_branch(ctx)
        second = await get_or_create_session_branch(ctx)

        assert first == second
        client.branch.create.assert_called_once()

    async def test_session_branch_not_stored_on_appcontext(self) -> None:
        """``AppContext`` must not expose a process-wide ``session_branch`` field."""
        # The architectural fix removes the field entirely. Test fails until the
        # field is gone, which is exactly the regression we want to prevent.
        config = ServerConfig(auth_mode="none")
        app_ctx = AppContext(client=MagicMock(), config=config)
        assert not hasattr(app_ctx, "session_branch")
