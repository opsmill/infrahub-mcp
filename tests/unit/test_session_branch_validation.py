"""Tests for session branch validation against stale cache.

Regression coverage for the bug where ``AppContext.session_branch`` is cached
for the lifetime of the MCP server process, but the underlying branch may
have been deleted on Infrahub (merged proposed change, manual delete, dev
server reset). Writes then 404 against the stale branch name until the
server process restarts.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from infrahub_sdk.exceptions import BranchNotFoundError

from infrahub_mcp.config import ServerConfig
from infrahub_mcp.utils import AppContext, get_or_create_session_branch


def _make_ctx(app_ctx: AppContext) -> MagicMock:
    """Create a mock FastMCP Context with the given AppContext."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    ctx.info = AsyncMock()
    ctx.warning = AsyncMock()
    ctx.debug = AsyncMock()
    return ctx


class TestGetOrCreateSessionBranch:
    async def test_returns_cached_branch_when_it_still_exists(self) -> None:
        """Cached branch is reused when it still exists on Infrahub — no re-create."""
        config = ServerConfig(auth_mode="none")
        app_ctx = AppContext(client=MagicMock(), config=config, session_branch="mcp/session-existing")

        client = MagicMock()
        client.branch.get = AsyncMock(return_value=MagicMock())
        client.branch.create = AsyncMock()

        ctx = _make_ctx(app_ctx)
        with patch("infrahub_mcp.utils.get_client", return_value=client):
            result = await get_or_create_session_branch(ctx)

        assert result == "mcp/session-existing"
        assert app_ctx.session_branch == "mcp/session-existing"
        client.branch.create.assert_not_called()
        client.branch.get.assert_called_once_with(branch_name="mcp/session-existing")

    async def test_recreates_when_cached_branch_was_deleted(self) -> None:
        """Stale cached branch (deleted on server) triggers creation of a new one."""
        config = ServerConfig(auth_mode="none", branch_pattern="mcp/session-{date}-{hex}")
        app_ctx = AppContext(client=MagicMock(), config=config, session_branch="mcp/session-stale")

        client = MagicMock()
        client.branch.get = AsyncMock(side_effect=BranchNotFoundError(identifier="mcp/session-stale"))
        client.branch.create = AsyncMock()

        ctx = _make_ctx(app_ctx)
        with patch("infrahub_mcp.utils.get_client", return_value=client):
            result = await get_or_create_session_branch(ctx)

        assert result != "mcp/session-stale"
        assert result.startswith("mcp/session-")
        assert app_ctx.session_branch == result
        client.branch.create.assert_called_once()

    async def test_creates_when_no_cached_branch(self) -> None:
        """First write of a process creates a new branch — no validation lookup."""
        config = ServerConfig(auth_mode="none", branch_pattern="mcp/session-{date}-{hex}")
        app_ctx = AppContext(client=MagicMock(), config=config, session_branch=None)

        client = MagicMock()
        client.branch.get = AsyncMock()
        client.branch.create = AsyncMock()

        ctx = _make_ctx(app_ctx)
        with patch("infrahub_mcp.utils.get_client", return_value=client):
            result = await get_or_create_session_branch(ctx)

        assert result.startswith("mcp/session-")
        assert app_ctx.session_branch == result
        client.branch.create.assert_called_once()
        client.branch.get.assert_not_called()
