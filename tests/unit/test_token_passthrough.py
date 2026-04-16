"""Tests for token-passthrough auth mode — ASGI middleware, get_client, and validation."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError

from infrahub_mcp.auth import _passthrough_token, set_passthrough_token
from infrahub_mcp.config import ServerConfig
from infrahub_mcp.server import _TokenPassthroughASGI, get_asgi_middleware
from infrahub_mcp.utils import AppContext, get_client


# ---------------------------------------------------------------------------
# _TokenPassthroughASGI — header extraction
# ---------------------------------------------------------------------------


class TestTokenPassthroughASGI:
    @pytest.mark.anyio
    async def test_extracts_bearer_token(self) -> None:
        app = AsyncMock()
        mw = _TokenPassthroughASGI(app, header="Authorization")

        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer my-secret-token")],
        }
        _passthrough_token.set(None)
        await mw(scope, MagicMock(), MagicMock())

        from infrahub_mcp.auth import get_passthrough_token

        assert get_passthrough_token() == "my-secret-token"
        _passthrough_token.set(None)

    @pytest.mark.anyio
    async def test_extracts_raw_token_without_bearer_prefix(self) -> None:
        app = AsyncMock()
        mw = _TokenPassthroughASGI(app, header="X-Infrahub-Token")

        scope = {
            "type": "http",
            "headers": [(b"x-infrahub-token", b"raw-api-key-123")],
        }
        _passthrough_token.set(None)
        await mw(scope, MagicMock(), MagicMock())

        from infrahub_mcp.auth import get_passthrough_token

        assert get_passthrough_token() == "raw-api-key-123"
        _passthrough_token.set(None)

    @pytest.mark.anyio
    async def test_no_token_header_leaves_contextvar_none(self) -> None:
        app = AsyncMock()
        mw = _TokenPassthroughASGI(app, header="Authorization")

        scope = {
            "type": "http",
            "headers": [],
        }
        _passthrough_token.set(None)
        await mw(scope, MagicMock(), MagicMock())

        from infrahub_mcp.auth import get_passthrough_token

        assert get_passthrough_token() is None
        _passthrough_token.set(None)

    @pytest.mark.anyio
    async def test_empty_bearer_leaves_contextvar_none(self) -> None:
        app = AsyncMock()
        mw = _TokenPassthroughASGI(app, header="Authorization")

        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer ")],
        }
        _passthrough_token.set(None)
        await mw(scope, MagicMock(), MagicMock())

        from infrahub_mcp.auth import get_passthrough_token

        assert get_passthrough_token() is None
        _passthrough_token.set(None)

    @pytest.mark.anyio
    async def test_non_http_scope_skipped(self) -> None:
        app = AsyncMock()
        mw = _TokenPassthroughASGI(app, header="Authorization")

        scope = {
            "type": "websocket",
            "headers": [(b"authorization", b"Bearer ws-token")],
        }
        _passthrough_token.set(None)
        await mw(scope, MagicMock(), MagicMock())

        from infrahub_mcp.auth import get_passthrough_token

        assert get_passthrough_token() is None
        _passthrough_token.set(None)

    @pytest.mark.anyio
    async def test_calls_inner_app(self) -> None:
        app = AsyncMock()
        mw = _TokenPassthroughASGI(app, header="Authorization")

        scope = {"type": "http", "headers": []}
        receive = MagicMock()
        send = MagicMock()
        await mw(scope, receive, send)
        app.assert_awaited_once_with(scope, receive, send)


# ---------------------------------------------------------------------------
# get_asgi_middleware
# ---------------------------------------------------------------------------


class TestGetAsgiMiddleware:
    def test_returns_middleware_in_passthrough_mode(self) -> None:
        with patch("infrahub_mcp.server._config", ServerConfig(auth_mode="token-passthrough")):
            result = get_asgi_middleware()
        assert len(result) == 1

    def test_returns_empty_in_none_mode(self) -> None:
        with patch("infrahub_mcp.server._config", ServerConfig(auth_mode="none")):
            result = get_asgi_middleware()
        assert result == []

    def test_returns_empty_in_oidc_mode(self) -> None:
        with patch("infrahub_mcp.server._config", ServerConfig(auth_mode="oidc")):
            result = get_asgi_middleware()
        assert result == []


# ---------------------------------------------------------------------------
# get_client — token-passthrough mode
# ---------------------------------------------------------------------------


def _make_ctx(app_ctx: AppContext) -> MagicMock:
    """Create a mock FastMCP Context with the given AppContext."""
    ctx = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    return ctx


class TestGetClientPassthrough:
    def test_raises_without_token(self) -> None:
        config = ServerConfig(auth_mode="token-passthrough")
        app_ctx = AppContext(client=None, config=config)
        ctx = _make_ctx(app_ctx)

        _passthrough_token.set(None)
        with pytest.raises(ToolError, match="Authentication required"):
            get_client(ctx)

    def test_creates_client_with_token(self) -> None:
        config = ServerConfig(auth_mode="token-passthrough")
        app_ctx = AppContext(client=None, config=config)
        ctx = _make_ctx(app_ctx)

        _passthrough_token.set(None)
        set_passthrough_token("test-api-token")
        with patch.dict(os.environ, {"INFRAHUB_ADDRESS": "http://localhost:8000"}):
            with patch("infrahub_sdk.client.InfrahubClient") as mock_cls:
                mock_client = MagicMock()
                mock_cls.return_value = mock_client
                result = get_client(ctx)

        assert result is mock_client
        mock_cls.assert_called_once_with(
            address="http://localhost:8000",
            config={"api_token": "test-api-token"},
        )
        _passthrough_token.set(None)

    def test_caches_client_in_app_context(self) -> None:
        config = ServerConfig(auth_mode="token-passthrough")
        app_ctx = AppContext(client=None, config=config)
        ctx = _make_ctx(app_ctx)

        _passthrough_token.set(None)
        set_passthrough_token("test-api-token")
        with patch.dict(os.environ, {"INFRAHUB_ADDRESS": "http://localhost:8000"}):
            with patch("infrahub_sdk.client.InfrahubClient") as mock_cls:
                mock_client = MagicMock()
                mock_cls.return_value = mock_client
                first = get_client(ctx)
                second = get_client(ctx)

        assert first is second
        mock_cls.assert_called_once()  # Only created once
        _passthrough_token.set(None)

    def test_shared_client_in_non_passthrough_mode(self) -> None:
        config = ServerConfig(auth_mode="none")
        shared_client = MagicMock()
        app_ctx = AppContext(client=shared_client, config=config)
        ctx = _make_ctx(app_ctx)

        result = get_client(ctx)
        assert result is shared_client

    def test_raises_when_shared_client_is_none(self) -> None:
        config = ServerConfig(auth_mode="none")
        app_ctx = AppContext(client=None, config=config)
        ctx = _make_ctx(app_ctx)

        with pytest.raises(ToolError, match="No Infrahub client available"):
            get_client(ctx)
