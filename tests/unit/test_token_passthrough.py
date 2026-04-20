"""Tests for token-passthrough auth mode — ASGI middleware, get_client, and validation."""

from __future__ import annotations

import os
from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp.exceptions import ToolError
from starlette.middleware import Middleware as StarletteMiddleware

from infrahub_mcp.auth import (
    _passthrough_basic,
    _passthrough_token,
    get_passthrough_basic,
    get_passthrough_token,
    set_passthrough_basic,
    set_passthrough_token,
)
from infrahub_mcp.config import ServerConfig
from infrahub_mcp.server import _CredentialsPassthroughASGI, _OAuthDiscoveryInterceptASGI, _decode_basic, get_asgi_middleware
from infrahub_mcp.utils import AppContext, get_client


@pytest.fixture(autouse=True)
def _clean_passthrough_contextvars() -> Generator[None]:
    """Isolate ContextVars between tests so failures don't leak."""
    token = _passthrough_token.set(None)
    basic = _passthrough_basic.set(None)
    yield
    _passthrough_token.reset(token)
    _passthrough_basic.reset(basic)


# ---------------------------------------------------------------------------
# _CredentialsPassthroughASGI — header extraction
# ---------------------------------------------------------------------------


class TestCredentialsPassthroughASGI:
    @pytest.mark.anyio
    async def test_extracts_bearer_token(self) -> None:
        captured: list[str | None] = []

        async def capture_app(scope: dict, receive: object, send: object) -> None:
            captured.append(get_passthrough_token())

        mw = _CredentialsPassthroughASGI(capture_app, header="Authorization")

        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer my-secret-token")],
        }
        await mw(scope, MagicMock(), MagicMock())

        assert captured == ["my-secret-token"]

    @pytest.mark.anyio
    async def test_extracts_raw_token_without_bearer_prefix(self) -> None:
        captured: list[str | None] = []

        async def capture_app(scope: dict, receive: object, send: object) -> None:
            captured.append(get_passthrough_token())

        mw = _CredentialsPassthroughASGI(capture_app, header="X-Infrahub-Token")

        scope = {
            "type": "http",
            "headers": [(b"x-infrahub-token", b"raw-api-key-123")],
        }
        await mw(scope, MagicMock(), MagicMock())

        assert captured == ["raw-api-key-123"]

    @pytest.mark.anyio
    async def test_raw_token_starting_with_bearer_is_not_stripped(self) -> None:
        """Tokens whose first 6 chars happen to be 'bearer' without a trailing
        space must NOT have the scheme stripped — that would corrupt them."""
        captured: list[str | None] = []

        async def capture_app(scope: dict, receive: object, send: object) -> None:
            captured.append(get_passthrough_token())

        mw = _CredentialsPassthroughASGI(capture_app, header="Authorization")

        scope = {
            "type": "http",
            "headers": [(b"authorization", b"bearertoken-xyz")],
        }
        await mw(scope, MagicMock(), MagicMock())

        assert captured == ["bearertoken-xyz"]

    @pytest.mark.anyio
    async def test_no_token_header_leaves_contextvar_none(self) -> None:
        app = AsyncMock()
        mw = _CredentialsPassthroughASGI(app, header="Authorization")

        scope = {
            "type": "http",
            "headers": [],
        }
        await mw(scope, MagicMock(), MagicMock())

        assert get_passthrough_token() is None

    @pytest.mark.anyio
    async def test_empty_bearer_leaves_contextvar_none(self) -> None:
        app = AsyncMock()
        mw = _CredentialsPassthroughASGI(app, header="Authorization")

        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer ")],
        }
        await mw(scope, MagicMock(), MagicMock())

        assert get_passthrough_token() is None

    @pytest.mark.anyio
    async def test_non_http_scope_skipped(self) -> None:
        app = AsyncMock()
        mw = _CredentialsPassthroughASGI(app, header="Authorization")

        scope = {
            "type": "websocket",
            "headers": [(b"authorization", b"Bearer ws-token")],
        }
        await mw(scope, MagicMock(), MagicMock())

        assert get_passthrough_token() is None

    @pytest.mark.anyio
    async def test_calls_inner_app(self) -> None:
        app = AsyncMock()
        mw = _CredentialsPassthroughASGI(app, header="Authorization")

        scope = {"type": "http", "headers": []}
        receive = MagicMock()
        send = MagicMock()
        await mw(scope, receive, send)
        app.assert_awaited_once_with(scope, receive, send)

    @pytest.mark.anyio
    async def test_resets_contextvar_after_request(self) -> None:
        """Token must not leak to subsequent requests."""
        app = AsyncMock()
        mw = _CredentialsPassthroughASGI(app, header="Authorization")

        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer request-token")],
        }
        await mw(scope, MagicMock(), MagicMock())

        # After the request completes, ContextVar should be reset to None
        assert get_passthrough_token() is None

    @pytest.mark.anyio
    async def test_resets_contextvar_on_inner_app_error(self) -> None:
        """Token must be cleared even when the inner app raises."""

        async def failing_app(scope: dict, receive: object, send: object) -> None:
            msg = "boom"
            raise RuntimeError(msg)

        mw = _CredentialsPassthroughASGI(failing_app, header="Authorization")

        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer error-token")],
        }
        with pytest.raises(RuntimeError, match="boom"):
            await mw(scope, MagicMock(), MagicMock())

        assert get_passthrough_token() is None

    @pytest.mark.anyio
    async def test_extracts_basic_credentials(self) -> None:
        import base64  # noqa: PLC0415

        captured: list[tuple[str, str] | None] = []

        async def capture_app(scope: dict, receive: object, send: object) -> None:
            captured.append(get_passthrough_basic())

        mw = _CredentialsPassthroughASGI(capture_app, header="Authorization")
        encoded = base64.b64encode(b"alice:s3cret").decode("ascii")

        scope = {
            "type": "http",
            "headers": [(b"authorization", f"Basic {encoded}".encode("latin-1"))],
        }
        await mw(scope, MagicMock(), MagicMock())

        assert captured == [("alice", "s3cret")]

    @pytest.mark.anyio
    async def test_malformed_basic_leaves_contextvar_none(self) -> None:
        app = AsyncMock()
        mw = _CredentialsPassthroughASGI(app, header="Authorization")

        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Basic !!!not-base64!!!")],
        }
        await mw(scope, MagicMock(), MagicMock())

        assert get_passthrough_basic() is None
        assert get_passthrough_token() is None

    @pytest.mark.anyio
    async def test_basic_missing_colon_leaves_contextvar_none(self) -> None:
        import base64  # noqa: PLC0415

        app = AsyncMock()
        mw = _CredentialsPassthroughASGI(app, header="Authorization")
        encoded = base64.b64encode(b"no-colon-here").decode("ascii")

        scope = {
            "type": "http",
            "headers": [(b"authorization", f"Basic {encoded}".encode("latin-1"))],
        }
        await mw(scope, MagicMock(), MagicMock())

        assert get_passthrough_basic() is None

    @pytest.mark.anyio
    async def test_resets_basic_contextvar_after_request(self) -> None:
        import base64  # noqa: PLC0415

        app = AsyncMock()
        mw = _CredentialsPassthroughASGI(app, header="Authorization")
        encoded = base64.b64encode(b"u:p").decode("ascii")

        scope = {
            "type": "http",
            "headers": [(b"authorization", f"Basic {encoded}".encode("latin-1"))],
        }
        await mw(scope, MagicMock(), MagicMock())

        assert get_passthrough_basic() is None


# ---------------------------------------------------------------------------
# _OAuthDiscoveryInterceptASGI — empty 404 for OAuth probes
# ---------------------------------------------------------------------------


class TestOAuthDiscoveryInterceptASGI:
    @pytest.mark.anyio
    async def test_intercepts_well_known_oauth_authorization_server(self) -> None:
        app = AsyncMock()
        mw = _OAuthDiscoveryInterceptASGI(app)

        sent_parts: list[dict] = []

        async def capture_send(message: dict) -> None:
            sent_parts.append(message)

        scope = {"type": "http", "path": "/.well-known/oauth-authorization-server"}
        await mw(scope, AsyncMock(), capture_send)

        app.assert_not_awaited()
        start = next(m for m in sent_parts if m["type"] == "http.response.start")
        assert start["status"] == 404
        body = next(m for m in sent_parts if m["type"] == "http.response.body")
        assert b'"invalid_request"' in body["body"]

    @pytest.mark.anyio
    async def test_intercepts_well_known_with_mcp_suffix(self) -> None:
        app = AsyncMock()
        mw = _OAuthDiscoveryInterceptASGI(app)

        sent_parts: list[dict] = []

        async def capture_send(message: dict) -> None:
            sent_parts.append(message)

        scope = {"type": "http", "path": "/.well-known/oauth-authorization-server/mcp"}
        await mw(scope, AsyncMock(), capture_send)

        app.assert_not_awaited()

    @pytest.mark.anyio
    async def test_intercepts_openid_configuration(self) -> None:
        app = AsyncMock()
        mw = _OAuthDiscoveryInterceptASGI(app)

        sent_parts: list[dict] = []

        async def capture_send(message: dict) -> None:
            sent_parts.append(message)

        scope = {"type": "http", "path": "/.well-known/openid-configuration"}
        await mw(scope, AsyncMock(), capture_send)

        app.assert_not_awaited()

    @pytest.mark.anyio
    async def test_intercepts_nested_well_known(self) -> None:
        app = AsyncMock()
        mw = _OAuthDiscoveryInterceptASGI(app)

        sent_parts: list[dict] = []

        async def capture_send(message: dict) -> None:
            sent_parts.append(message)

        scope = {"type": "http", "path": "/mcp/.well-known/openid-configuration"}
        await mw(scope, AsyncMock(), capture_send)

        app.assert_not_awaited()

    @pytest.mark.anyio
    async def test_intercepts_register(self) -> None:
        app = AsyncMock()
        mw = _OAuthDiscoveryInterceptASGI(app)

        sent_parts: list[dict] = []

        async def capture_send(message: dict) -> None:
            sent_parts.append(message)

        scope = {"type": "http", "path": "/register"}
        await mw(scope, AsyncMock(), capture_send)

        app.assert_not_awaited()

    @pytest.mark.anyio
    async def test_passes_through_normal_paths(self) -> None:
        app = AsyncMock()
        mw = _OAuthDiscoveryInterceptASGI(app)

        scope = {"type": "http", "path": "/health"}
        receive = AsyncMock()
        send = AsyncMock()
        await mw(scope, receive, send)

        app.assert_awaited_once()

    @pytest.mark.anyio
    async def test_passes_through_mcp_endpoint(self) -> None:
        app = AsyncMock()
        mw = _OAuthDiscoveryInterceptASGI(app)

        scope = {"type": "http", "path": "/mcp"}
        receive = AsyncMock()
        send = AsyncMock()
        await mw(scope, receive, send)

        app.assert_awaited_once()

    @pytest.mark.anyio
    async def test_passes_through_non_http_scope(self) -> None:
        app = AsyncMock()
        mw = _OAuthDiscoveryInterceptASGI(app)

        scope = {"type": "websocket", "path": "/.well-known/oauth-authorization-server"}
        receive = AsyncMock()
        send = AsyncMock()
        await mw(scope, receive, send)

        app.assert_awaited_once()


# ---------------------------------------------------------------------------
# get_asgi_middleware
# ---------------------------------------------------------------------------


class TestGetAsgiMiddleware:
    def test_returns_both_middlewares_in_passthrough_mode(self) -> None:
        with patch("infrahub_mcp.server._config", ServerConfig(auth_mode="token-passthrough")):
            result = get_asgi_middleware()
        assert len(result) == 2
        assert all(isinstance(m, StarletteMiddleware) for m in result)
        assert result[0].cls is _CredentialsPassthroughASGI  # type: ignore[attr-defined]
        assert result[1].cls is _OAuthDiscoveryInterceptASGI  # type: ignore[attr-defined]

    def test_returns_both_middlewares_in_basic_passthrough_mode(self) -> None:
        with patch("infrahub_mcp.server._config", ServerConfig(auth_mode="basic-passthrough")):
            result = get_asgi_middleware()
        assert len(result) == 2
        assert all(isinstance(m, StarletteMiddleware) for m in result)
        assert result[0].cls is _CredentialsPassthroughASGI  # type: ignore[attr-defined]
        assert result[1].cls is _OAuthDiscoveryInterceptASGI  # type: ignore[attr-defined]

    def test_returns_oauth_intercept_in_none_mode(self) -> None:
        with patch("infrahub_mcp.server._config", ServerConfig(auth_mode="none")):
            result = get_asgi_middleware()
        assert len(result) == 1
        assert isinstance(result[0], StarletteMiddleware)
        assert result[0].cls is _OAuthDiscoveryInterceptASGI  # type: ignore[attr-defined]

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


@pytest.fixture()
def infrahub_env() -> Generator[None]:
    """Provide a minimal INFRAHUB_ADDRESS env for passthrough tests."""
    with patch.dict(os.environ, {"INFRAHUB_ADDRESS": "http://localhost:8000"}):
        yield


@pytest.fixture()
def token_passthrough_ctx() -> MagicMock:
    """Mock Context wired for token-passthrough mode."""
    config = ServerConfig(auth_mode="token-passthrough")
    return _make_ctx(AppContext(client=None, config=config))


@pytest.fixture()
def basic_passthrough_ctx() -> MagicMock:
    """Mock Context wired for basic-passthrough mode."""
    config = ServerConfig(auth_mode="basic-passthrough")
    return _make_ctx(AppContext(client=None, config=config))


class TestGetClientPassthrough:
    def test_raises_without_token(self, infrahub_env: None, token_passthrough_ctx: MagicMock) -> None:
        with pytest.raises(ToolError, match="Authentication required"):
            get_client(token_passthrough_ctx)

    def test_creates_client_with_token(self, infrahub_env: None, token_passthrough_ctx: MagicMock) -> None:
        set_passthrough_token("test-api-token")
        with patch("infrahub_mcp.utils.InfrahubClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            result = get_client(token_passthrough_ctx)

        assert result is mock_client
        mock_cls.assert_called_once_with(
            address="http://localhost:8000",
            config={"api_token": "test-api-token"},
        )

    def test_creates_fresh_client_per_call(self, infrahub_env: None, token_passthrough_ctx: MagicMock) -> None:
        """Each get_client() call creates a new InfrahubClient so different
        tokens are never mixed across requests."""
        set_passthrough_token("token-a")
        with patch("infrahub_mcp.utils.InfrahubClient") as mock_cls:
            client_a = MagicMock()
            client_b = MagicMock()
            mock_cls.side_effect = [client_a, client_b]
            first = get_client(token_passthrough_ctx)
            second = get_client(token_passthrough_ctx)

        assert first is not second
        assert mock_cls.call_count == 2

    def test_shared_client_in_non_passthrough_mode(self) -> None:
        config = ServerConfig(auth_mode="none")
        shared_client = MagicMock()
        ctx = _make_ctx(AppContext(client=shared_client, config=config))

        result = get_client(ctx)
        assert result is shared_client

    def test_raises_without_basic_credentials(self, infrahub_env: None, basic_passthrough_ctx: MagicMock) -> None:
        with pytest.raises(ToolError, match="Basic credentials"):
            get_client(basic_passthrough_ctx)

    def test_creates_client_with_basic_credentials(self, infrahub_env: None, basic_passthrough_ctx: MagicMock) -> None:
        set_passthrough_basic(("alice", "s3cret"))
        with patch("infrahub_mcp.utils.InfrahubClient") as mock_cls:
            mock_client = MagicMock()
            mock_cls.return_value = mock_client
            result = get_client(basic_passthrough_ctx)

        assert result is mock_client
        mock_cls.assert_called_once_with(
            address="http://localhost:8000",
            config={"username": "alice", "password": "s3cret"},
        )

    @pytest.mark.parametrize("mode", ["token-passthrough", "basic-passthrough"])
    def test_raises_without_infrahub_address(self, mode: str) -> None:
        config = ServerConfig(auth_mode=mode)
        ctx = _make_ctx(AppContext(client=None, config=config))

        if mode == "token-passthrough":
            set_passthrough_token("some-token")
        else:
            set_passthrough_basic(("user", "pass"))

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ToolError, match="INFRAHUB_ADDRESS is required"):
                get_client(ctx)

    def test_raises_when_shared_client_is_none(self) -> None:
        config = ServerConfig(auth_mode="none")
        ctx = _make_ctx(AppContext(client=None, config=config))

        with pytest.raises(ToolError, match="No Infrahub client available"):
            get_client(ctx)


# ---------------------------------------------------------------------------
# _decode_basic — Base64 credential parsing
# ---------------------------------------------------------------------------


class TestDecodeBasic:
    def test_valid_credentials(self) -> None:
        import base64  # noqa: PLC0415

        encoded = base64.b64encode(b"alice:s3cret").decode("ascii")
        assert _decode_basic(encoded) == ("alice", "s3cret")

    def test_password_with_colons(self) -> None:
        import base64  # noqa: PLC0415

        encoded = base64.b64encode(b"admin:pass:with:colons").decode("ascii")
        assert _decode_basic(encoded) == ("admin", "pass:with:colons")

    def test_empty_password(self) -> None:
        import base64  # noqa: PLC0415

        encoded = base64.b64encode(b"user:").decode("ascii")
        assert _decode_basic(encoded) == ("user", "")

    def test_invalid_base64_returns_none(self) -> None:
        assert _decode_basic("!!!not-base64!!!") is None

    def test_missing_colon_returns_none(self) -> None:
        import base64  # noqa: PLC0415

        encoded = base64.b64encode(b"nocolon").decode("ascii")
        assert _decode_basic(encoded) is None

    def test_empty_string_returns_none(self) -> None:
        assert _decode_basic("") is None
