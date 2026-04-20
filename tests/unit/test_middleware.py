"""Tests for the Infrahub MCP middleware stack."""

from __future__ import annotations

import json
import logging
from collections.abc import Generator, Sequence
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import mcp.types as mt
import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware.error_handling import RetryMiddleware
from fastmcp.server.middleware.middleware import MiddlewareContext
from fastmcp.tools.base import ToolResult
from infrahub_sdk.exceptions import AuthenticationError, ServerNotReachableError, ServerNotResponsiveError
from mcp import McpError
from mcp.types import TextContent

import infrahub_mcp.middleware as middleware_module
from infrahub_mcp.auth import _passthrough_token, set_passthrough_token
from infrahub_mcp.config import ServerConfig
from infrahub_mcp.middleware import (
    WRITE_TAG,
    AuditMiddleware,
    InfrahubConnectionMiddleware,
    MetricsMiddleware,
    OTelTracingMiddleware,
    ReadOnlyMiddleware,
    RequestIdMiddleware,
    SafeRetryMiddleware,
    StrictResponseLimitingMiddleware,
    TokenPassthroughMiddleware,
    configure_middleware,
    get_caching_middleware,
    get_error_handling,
    get_metrics,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_tool_context(
    tool_name: str,
) -> MiddlewareContext[mt.CallToolRequestParams]:
    """Create a MiddlewareContext for a tool call."""
    params = mt.CallToolRequestParams(name=tool_name, arguments={})
    return MiddlewareContext(
        message=params,
        method="tools/call",
    )


def _make_list_tools_context() -> MiddlewareContext[mt.ListToolsRequest]:
    """Create a MiddlewareContext for listing tools."""
    return MiddlewareContext(
        message=mt.ListToolsRequest(method="tools/list"),
        method="tools/list",
    )


def _make_resource_context(
    uri: str,
) -> MiddlewareContext[mt.ReadResourceRequestParams]:
    """Create a MiddlewareContext for reading a resource."""
    params = mt.ReadResourceRequestParams(uri=mt.AnyUrl(uri))
    return MiddlewareContext(
        message=params,
        method="resources/read",
    )


class _FakeTool:
    """Lightweight stand-in for fastmcp Tool in middleware tests."""

    def __init__(
        self,
        name: str,
        *,
        tags: set[str] | None = None,
        annotations: mt.ToolAnnotations | None = None,
    ) -> None:
        self.name = name
        self.tags = tags or set()
        self.annotations = annotations


def _make_tool(name: str, *, tags: set[str] | None = None) -> Any:
    """Create a minimal object with ``name`` and ``tags`` for testing."""
    return _FakeTool(name, tags=tags)


# ---------------------------------------------------------------------------
# RequestIdMiddleware
# ---------------------------------------------------------------------------


class TestRequestIdMiddleware:
    @pytest.mark.anyio
    async def test_injects_request_id_in_logs(self, caplog: pytest.LogCaptureFixture) -> None:
        middleware = RequestIdMiddleware()
        ctx = _make_tool_context("get_schema")

        async def call_next(c: MiddlewareContext[Any]) -> str:
            return "ok"

        with caplog.at_level(logging.INFO, logger="infrahub_mcp.middleware"):
            result = await middleware.on_message(ctx, call_next)

        assert result == "ok"
        assert any("request_start" in r.message for r in caplog.records)
        assert any("request_end" in r.message for r in caplog.records)
        assert any("request_id=" in r.message for r in caplog.records)

    @pytest.mark.anyio
    async def test_logs_error_status_on_failure(self, caplog: pytest.LogCaptureFixture) -> None:
        middleware = RequestIdMiddleware()
        ctx = _make_tool_context("get_schema")

        async def call_next(c: MiddlewareContext[Any]) -> str:
            msg = "boom"
            raise RuntimeError(msg)

        with caplog.at_level(logging.WARNING, logger="infrahub_mcp.middleware"):
            with pytest.raises(RuntimeError, match="boom"):
                await middleware.on_message(ctx, call_next)

        assert any("status=error" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# ReadOnlyMiddleware — tag-based filtering
# ---------------------------------------------------------------------------


class TestReadOnlyMiddleware:
    @pytest.mark.anyio
    async def test_filters_write_tagged_tools_from_listing(self) -> None:
        middleware = ReadOnlyMiddleware()
        all_tools = [
            _make_tool("get_schema", tags={"schema", "retrieve"}),
            _make_tool("get_nodes", tags={"nodes", "retrieve"}),
            _make_tool("node_upsert", tags={"nodes", WRITE_TAG}),
            _make_tool("node_delete", tags={"nodes", WRITE_TAG}),
            _make_tool("query_graphql", tags={"graphql", "retrieve"}),
        ]

        async def call_next(
            c: MiddlewareContext[Any],
        ) -> Sequence[Any]:
            return all_tools

        ctx = _make_list_tools_context()
        result = await middleware.on_list_tools(ctx, call_next)

        names = [t.name for t in result]
        assert "get_schema" in names
        assert "get_nodes" in names
        assert "query_graphql" in names
        assert "node_upsert" not in names
        assert "node_delete" not in names

    @pytest.mark.anyio
    async def test_allows_tool_without_write_tag(self) -> None:
        """A tool without the 'write' tag passes through even if name is suspicious."""
        middleware = ReadOnlyMiddleware()
        all_tools = [
            _make_tool("write_report", tags={"reports", "generate"}),
        ]

        async def call_next(c: MiddlewareContext[Any]) -> Sequence[Any]:
            return all_tools

        ctx = _make_list_tools_context()
        result = await middleware.on_list_tools(ctx, call_next)
        assert len(result) == 1

    @pytest.mark.anyio
    async def test_blocks_write_tool_call_without_context(self) -> None:
        """Without fastmcp_context, falls back to hardcoded name check."""
        middleware = ReadOnlyMiddleware()
        ctx = _make_tool_context("node_upsert")

        async def call_next(c: MiddlewareContext[Any]) -> ToolResult:
            msg = "should not reach here"
            raise AssertionError(msg)

        with pytest.raises(McpError, match="read-only mode"):
            await middleware.on_call_tool(ctx, call_next)

    @pytest.mark.anyio
    async def test_allows_read_tool_call(self) -> None:
        middleware = ReadOnlyMiddleware()
        ctx = _make_tool_context("get_schema")
        expected = ToolResult(content=[])

        async def call_next(c: MiddlewareContext[Any]) -> ToolResult:
            return expected

        result = await middleware.on_call_tool(ctx, call_next)
        assert result is expected

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "tool_name",
        ["node_upsert", "node_delete", "propose_changes", "mutate_graphql"],
    )
    async def test_blocks_known_write_tools_without_context(self, tool_name: str) -> None:
        """Fail-closed fallback blocks write tools not in the read-only allowlist."""
        middleware = ReadOnlyMiddleware()
        ctx = _make_tool_context(tool_name)

        async def call_next(c: MiddlewareContext[Any]) -> ToolResult:
            msg = "should not reach here"
            raise AssertionError(msg)

        with pytest.raises(McpError):
            await middleware.on_call_tool(ctx, call_next)

    @pytest.mark.anyio
    async def test_blocks_unknown_tool_without_context(self) -> None:
        """Fail-closed: an unknown tool not in the read-only allowlist is blocked."""
        middleware = ReadOnlyMiddleware()
        ctx = _make_tool_context("some_future_write_tool")

        async def call_next(c: MiddlewareContext[Any]) -> ToolResult:
            msg = "should not reach here"
            raise AssertionError(msg)

        with pytest.raises(McpError, match="read-only mode"):
            await middleware.on_call_tool(ctx, call_next)

    @pytest.mark.anyio
    @pytest.mark.parametrize(
        "tool_name",
        ["get_schema", "query_graphql", "get_nodes", "search_nodes"],
    )
    async def test_allows_known_read_tools_without_context(self, tool_name: str) -> None:
        """Fail-closed fallback permits all known read-only tools."""
        middleware = ReadOnlyMiddleware()
        ctx = _make_tool_context(tool_name)
        expected = ToolResult(content=[])

        async def call_next(c: MiddlewareContext[Any]) -> ToolResult:
            return expected

        result = await middleware.on_call_tool(ctx, call_next)
        assert result is expected


# ---------------------------------------------------------------------------
# AuditMiddleware
# ---------------------------------------------------------------------------


class TestAuditMiddleware:
    @pytest.mark.anyio
    async def test_logs_tool_call(self, caplog: pytest.LogCaptureFixture) -> None:
        middleware = AuditMiddleware()
        ctx = _make_tool_context("get_nodes")
        expected = ToolResult(content=[])

        async def call_next(c: MiddlewareContext[Any]) -> ToolResult:
            return expected

        with caplog.at_level(logging.INFO, logger="infrahub_mcp.middleware"):
            result = await middleware.on_call_tool(ctx, call_next)

        assert result is expected
        assert any("tool_call" in r.message for r in caplog.records)
        assert any("tool=get_nodes" in r.message for r in caplog.records)

    @pytest.mark.anyio
    async def test_logs_resource_read(self, caplog: pytest.LogCaptureFixture) -> None:
        middleware = AuditMiddleware()
        ctx = _make_resource_context("infrahub://schema")

        async def call_next(c: MiddlewareContext[Any]) -> str:
            return "data"

        with caplog.at_level(logging.INFO, logger="infrahub_mcp.middleware"):
            result = await middleware.on_read_resource(ctx, call_next)

        assert result == "data"
        assert any("resource_read" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# MetricsMiddleware
# ---------------------------------------------------------------------------


class TestMetricsMiddleware:
    @pytest.mark.anyio
    async def test_counts_requests(self) -> None:
        middleware = MetricsMiddleware()
        ctx = _make_tool_context("get_schema")

        async def call_next(c: MiddlewareContext[Any]) -> str:
            return "ok"

        await middleware.on_message(ctx, call_next)
        await middleware.on_message(ctx, call_next)

        snap = middleware.snapshot()
        assert snap["requests"]["tools/call"] == 2
        assert snap["errors"].get("tools/call", 0) == 0

    @pytest.mark.anyio
    async def test_counts_errors(self) -> None:
        middleware = MetricsMiddleware()
        ctx = _make_tool_context("get_schema")

        async def call_next(c: MiddlewareContext[Any]) -> str:
            msg = "fail"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError):
            await middleware.on_message(ctx, call_next)

        snap = middleware.snapshot()
        assert snap["requests"]["tools/call"] == 1
        assert snap["errors"]["tools/call"] == 1

    @pytest.mark.anyio
    async def test_tracks_latency(self) -> None:
        middleware = MetricsMiddleware()
        ctx = _make_tool_context("get_schema")

        async def call_next(c: MiddlewareContext[Any]) -> str:
            return "ok"

        await middleware.on_message(ctx, call_next)

        snap = middleware.snapshot()
        assert "tools/call" in snap["latency_ms"]
        assert snap["latency_ms"]["tools/call"] >= 0

    def test_snapshot_is_serializable(self) -> None:
        middleware = MetricsMiddleware()
        snap = middleware.snapshot()
        # Should not raise
        json.dumps(snap)

    @pytest.mark.anyio
    async def test_prometheus_text_format(self) -> None:
        middleware = MetricsMiddleware()
        ctx = _make_tool_context("get_schema")

        async def call_next(c: MiddlewareContext[Any]) -> str:
            return "ok"

        await middleware.on_message(ctx, call_next)

        text = middleware.prometheus_text()
        assert "infrahub_mcp_requests_total" in text
        assert 'method="tools/call"' in text
        assert "# TYPE infrahub_mcp_requests_total counter" in text
        assert "# HELP infrahub_mcp_requests_total" in text

    @pytest.mark.anyio
    async def test_prometheus_text_includes_errors(self) -> None:
        middleware = MetricsMiddleware()
        ctx = _make_tool_context("get_schema")

        async def call_next(c: MiddlewareContext[Any]) -> str:
            msg = "fail"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError):
            await middleware.on_message(ctx, call_next)

        text = middleware.prometheus_text()
        assert "infrahub_mcp_errors_total" in text

    def test_prometheus_text_empty(self) -> None:
        middleware = MetricsMiddleware()
        text = middleware.prometheus_text()
        assert "infrahub_mcp_requests_total" in text
        assert text.endswith("\n")


# ---------------------------------------------------------------------------
# OTelTracingMiddleware
# ---------------------------------------------------------------------------


class TestOTelTracingMiddleware:
    @pytest.mark.anyio
    async def test_passes_through_when_otel_unavailable(self) -> None:
        """When opentelemetry is not installed, middleware is a no-op."""
        middleware = OTelTracingMiddleware()
        ctx = _make_tool_context("get_schema")

        async def call_next(c: MiddlewareContext[Any]) -> str:
            return "ok"

        # Even if otel is not installed, this should work
        result = await middleware.on_message(ctx, call_next)
        assert result == "ok"

    @pytest.mark.anyio
    async def test_propagates_errors(self) -> None:
        """Errors should propagate through the middleware."""
        middleware = OTelTracingMiddleware()
        ctx = _make_tool_context("get_schema")

        async def call_next(c: MiddlewareContext[Any]) -> str:
            msg = "fail"
            raise RuntimeError(msg)

        with pytest.raises(RuntimeError, match="fail"):
            await middleware.on_message(ctx, call_next)


# ---------------------------------------------------------------------------
# configure_middleware
# ---------------------------------------------------------------------------


@pytest.fixture
def _reset_middleware_globals() -> Generator[None]:
    """Reset module-level middleware state before and after each test."""
    middleware_module._metrics = None  # noqa: SLF001
    middleware_module._error_handling = None  # noqa: SLF001
    middleware_module._caching_middleware = None  # noqa: SLF001
    yield
    middleware_module._metrics = None  # noqa: SLF001
    middleware_module._error_handling = None  # noqa: SLF001
    middleware_module._caching_middleware = None  # noqa: SLF001


@pytest.mark.usefixtures("_reset_middleware_globals")
class TestConfigureMiddleware:
    def test_registers_middleware_read_write_mode(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig(read_only=False)
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "ReadOnlyMiddleware" not in types
        assert "RequestIdMiddleware" in types
        assert "MetricsMiddleware" in types
        assert "AuditMiddleware" in types
        assert "ErrorHandlingMiddleware" in types

    def test_registers_middleware_read_only_mode(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig(read_only=True)
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "ReadOnlyMiddleware" in types

    def test_debug_mode_enables_tracebacks(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig(log_level="debug")
        configure_middleware(mock_mcp, config)

        error_mw = next(m for m in mock_mcp.middleware if type(m).__name__ == "ErrorHandlingMiddleware")
        assert error_mw.include_traceback is True

    def test_rate_limiting_enabled(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig(rate_limit_rps=10.0, rate_limit_burst=20)
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "RateLimitingMiddleware" in types

    def test_rate_limiting_disabled_by_default(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig()
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "RateLimitingMiddleware" not in types

    def test_retry_middleware_enabled(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig(retry_max_attempts=3, retry_base_delay=0.5)
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "SafeRetryMiddleware" in types

    def test_retry_middleware_disabled_by_default(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig()
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "RetryMiddleware" not in types

    def test_cache_middleware_enabled(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig(cache_enabled=True, cache_list_ttl=60, cache_read_ttl=120)
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "ResponseCachingMiddleware" in types

    def test_cache_middleware_disabled_by_default(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig()
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "ResponseCachingMiddleware" not in types

    def test_otel_middleware_enabled(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig(otel_enabled=True)
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "OTelTracingMiddleware" in types

    def test_otel_middleware_disabled_by_default(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig()
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "OTelTracingMiddleware" not in types

    def test_dereference_middleware_enabled(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig(dereference_schemas=True)
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "DereferenceRefsMiddleware" in types

    def test_dereference_middleware_disabled_by_default(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig()
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "DereferenceRefsMiddleware" not in types

    def test_ping_middleware_enabled(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig(ping_interval_ms=5000)
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "PingMiddleware" in types

    def test_ping_middleware_disabled_by_default(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig()
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "PingMiddleware" not in types

    def test_auth_middleware_enabled_in_oidc_mode(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig(auth_mode="oidc", auth_scopes_write="infrahub:write,admin")
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "AuthMiddleware" in types

    def test_auth_middleware_disabled_by_default(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig()
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "AuthMiddleware" not in types

    def test_auth_middleware_disabled_without_oidc_even_with_scopes(self) -> None:
        """auth_scopes_write alone (without OIDC) should not enable AuthMiddleware."""
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig(auth_mode="none", auth_scopes_write="write,admin")
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "AuthMiddleware" not in types

    def test_all_middleware_enabled(self) -> None:
        """Smoke test: enable all optional middleware at once."""
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig(
            read_only=True,
            log_level="debug",
            rate_limit_rps=10.0,
            rate_limit_burst=20,
            retry_max_attempts=3,
            cache_enabled=True,
            otel_enabled=True,
            dereference_schemas=True,
            ping_interval_ms=5000,
            auth_mode="oidc",
            auth_scopes_write="write",
        )
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "RateLimitingMiddleware" in types
        assert "SafeRetryMiddleware" in types
        assert "ResponseCachingMiddleware" in types
        assert "OTelTracingMiddleware" in types
        assert "DereferenceRefsMiddleware" in types
        assert "PingMiddleware" in types
        assert "AuthMiddleware" in types
        assert "ReadOnlyMiddleware" in types

    def test_rate_limit_auto_burst(self) -> None:
        """Burst capacity auto-calculated as 2x RPS when not specified."""
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig(rate_limit_rps=10.0, rate_limit_burst=0)
        configure_middleware(mock_mcp, config)

        rate_limiter = next(m for m in mock_mcp.middleware if type(m).__name__ == "RateLimitingMiddleware")
        assert rate_limiter.burst_capacity == 20  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Module-level getters
# ---------------------------------------------------------------------------


@pytest.mark.usefixtures("_reset_middleware_globals")
class TestModuleLevelGetters:
    def test_get_metrics_after_configure(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []
        mock_mcp.add_middleware.side_effect = lambda mw: mock_mcp.middleware.append(mw)

        config = ServerConfig()
        configure_middleware(mock_mcp, config)

        assert get_metrics() is not None

    def test_get_error_handling_after_configure(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []
        mock_mcp.add_middleware.side_effect = lambda mw: mock_mcp.middleware.append(mw)

        config = ServerConfig()
        configure_middleware(mock_mcp, config)

        assert get_error_handling() is not None

    def test_get_caching_middleware_when_disabled(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []
        mock_mcp.add_middleware.side_effect = lambda mw: mock_mcp.middleware.append(mw)

        config = ServerConfig(cache_enabled=False)
        configure_middleware(mock_mcp, config)

        assert get_caching_middleware() is None
        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "ResponseCachingMiddleware" not in types

    def test_get_caching_middleware_when_enabled(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []
        mock_mcp.add_middleware.side_effect = lambda mw: mock_mcp.middleware.append(mw)

        config = ServerConfig(cache_enabled=True)
        configure_middleware(mock_mcp, config)

        assert get_caching_middleware() is not None


# ---------------------------------------------------------------------------
# AuditMiddleware — user-aware logging
# ---------------------------------------------------------------------------


class TestAuditMiddlewareUser:
    @pytest.mark.anyio
    async def test_audit_tool_call_includes_user(self) -> None:
        """Audit log for tool calls should include user identity."""
        middleware = AuditMiddleware(user_claim="email")
        ctx = _make_tool_context("get_nodes")
        expected = ToolResult(content=[])

        async def fake_call_next(c: MiddlewareContext[Any]) -> ToolResult:
            return expected

        with patch("infrahub_mcp.middleware.get_user_from_token", return_value="alice-example.com"):
            with patch("infrahub_mcp.middleware.logger") as mock_logger:
                result = await middleware.on_call_tool(ctx, fake_call_next)
                mock_logger.info.assert_called_once_with("tool_call tool=%s user=%s", "get_nodes", "alice-example.com")

        assert result is expected

    @pytest.mark.anyio
    async def test_audit_resource_read_includes_user(self) -> None:
        """Audit log for resource reads should include user identity."""
        middleware = AuditMiddleware(user_claim="email")
        ctx = _make_resource_context("infrahub://schema")

        async def fake_call_next(c: MiddlewareContext[Any]) -> str:
            return "data"

        with patch("infrahub_mcp.middleware.get_user_from_token", return_value="bob-example.com"):
            with patch("infrahub_mcp.middleware.logger") as mock_logger:
                result = await middleware.on_read_resource(ctx, fake_call_next)
                mock_logger.info.assert_called_once()
                call_args = mock_logger.info.call_args
                assert call_args[0][0] == "resource_read uri=%s user=%s"
                assert str(call_args[0][1]) == "infrahub://schema"
                assert call_args[0][2] == "bob-example.com"

        assert result == "data"

    @pytest.mark.anyio
    async def test_audit_forwards_custom_user_claim(self) -> None:
        """AuditMiddleware should forward the configured claim to get_user_from_token."""
        middleware = AuditMiddleware(user_claim="preferred_username")
        ctx = _make_tool_context("get_nodes")
        expected = ToolResult(content=[])

        async def fake_call_next(c: MiddlewareContext[Any]) -> ToolResult:
            return expected

        with patch("infrahub_mcp.middleware.get_user_from_token", return_value="jdoe") as mock_get_user:
            await middleware.on_call_tool(ctx, fake_call_next)
            mock_get_user.assert_called_once_with(claim="preferred_username")

    @pytest.mark.anyio
    async def test_audit_no_claim_returns_anonymous(self) -> None:
        """AuditMiddleware without user_claim should log anonymous without calling get_user_from_token."""
        middleware = AuditMiddleware()
        ctx = _make_tool_context("get_nodes")
        expected = ToolResult(content=[])

        async def fake_call_next(c: MiddlewareContext[Any]) -> ToolResult:
            return expected

        with patch("infrahub_mcp.middleware.get_user_from_token") as mock_get_user:
            with patch("infrahub_mcp.middleware.logger") as mock_logger:
                await middleware.on_call_tool(ctx, fake_call_next)
                mock_get_user.assert_not_called()
                mock_logger.info.assert_called_once_with("tool_call tool=%s user=%s", "get_nodes", "anonymous")


# ---------------------------------------------------------------------------
# configure_middleware — AuthMiddleware auto-enable in OIDC mode
# ---------------------------------------------------------------------------


class TestConfigureMiddlewareOidc:
    def test_auth_middleware_auto_enabled_in_oidc_mode(self) -> None:
        """AuthMiddleware should be auto-enabled when auth_mode=oidc, even without auth_scopes_write."""
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig(auth_mode="oidc", auth_scopes_write="")
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "AuthMiddleware" in types

    def test_auth_middleware_uses_default_write_scope_in_oidc(self) -> None:
        """In OIDC mode without explicit scopes, default scope should be 'write'."""
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig(auth_mode="oidc", auth_scopes_write="")
        configure_middleware(mock_mcp, config)

        # Verify AuthMiddleware was added (scope correctness is covered by the integration)
        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "AuthMiddleware" in types

    def test_auth_middleware_respects_explicit_scopes_in_oidc(self) -> None:
        """In OIDC mode with explicit scopes, those scopes should be used."""
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig(auth_mode="oidc", auth_scopes_write="infrahub:write,admin")
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "AuthMiddleware" in types


# ---------------------------------------------------------------------------
# SafeRetryMiddleware — on_call_tool routing
# ---------------------------------------------------------------------------


def _make_retry_tool_context(
    tool_name: str,
    tool: Any,
) -> MiddlewareContext[mt.CallToolRequestParams]:
    """Create a tool context with a fastmcp_context that returns *tool*."""
    mock_fastmcp = MagicMock()
    mock_fastmcp.get_tool = AsyncMock(return_value=tool)
    mock_ctx = MagicMock()
    mock_ctx.fastmcp = mock_fastmcp
    params = mt.CallToolRequestParams(name=tool_name, arguments={})
    return MiddlewareContext(
        message=params,
        method="tools/call",
        fastmcp_context=mock_ctx,
    )


class TestSafeRetryMiddlewareRouting:
    """Verify that SafeRetryMiddleware retries safe tools and skips unsafe ones."""

    @pytest.mark.anyio
    async def test_read_only_tool_is_retried(self) -> None:
        """Tools with readOnlyHint=True should be delegated to parent retry logic."""
        tool = _FakeTool(
            "get_schema",
            annotations=mt.ToolAnnotations(readOnlyHint=True),
        )
        ctx = _make_retry_tool_context("get_schema", tool)
        mw = SafeRetryMiddleware(max_retries=2, base_delay=0)

        call_next_called = False

        async def call_next(_: Any) -> ToolResult:
            nonlocal call_next_called
            call_next_called = True
            return ToolResult(content=[])

        with patch.object(RetryMiddleware, "on_call_tool", return_value=ToolResult(content=[])) as mock_super:
            await mw.on_call_tool(ctx, call_next)
            assert mock_super.called, "Should delegate to parent retry logic"
            assert not call_next_called, "Should NOT call call_next directly"

    @pytest.mark.anyio
    async def test_idempotent_tool_is_retried(self) -> None:
        """Tools with idempotentHint=True should be delegated to parent retry logic."""
        tool = _FakeTool(
            "some_idempotent_tool",
            annotations=mt.ToolAnnotations(idempotentHint=True),
        )
        ctx = _make_retry_tool_context("some_idempotent_tool", tool)
        mw = SafeRetryMiddleware(max_retries=2, base_delay=0)

        with patch.object(RetryMiddleware, "on_call_tool", return_value=ToolResult(content=[])) as mock_super:
            await mw.on_call_tool(ctx, call_next=MagicMock())
            assert mock_super.called

    @pytest.mark.anyio
    async def test_non_safe_tool_skips_retry(self) -> None:
        """Mutating tools (not read-only, not idempotent) bypass retry logic."""
        tool = _FakeTool(
            "node_upsert",
            annotations=mt.ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=False),
        )
        ctx = _make_retry_tool_context("node_upsert", tool)
        mw = SafeRetryMiddleware(max_retries=2, base_delay=0)

        sentinel = ToolResult(content=[])

        async def call_next(_: Any) -> ToolResult:
            return sentinel

        result = await mw.on_call_tool(ctx, call_next)
        assert result is sentinel, "Should call through directly without retry"

    @pytest.mark.anyio
    async def test_tool_without_annotations_skips_retry(self) -> None:
        """Tools with no annotations should not be retried (safe default)."""
        tool = _FakeTool("unknown_tool")
        ctx = _make_retry_tool_context("unknown_tool", tool)
        mw = SafeRetryMiddleware(max_retries=2, base_delay=0)

        sentinel = ToolResult(content=[])

        async def call_next(_: Any) -> ToolResult:
            return sentinel

        result = await mw.on_call_tool(ctx, call_next)
        assert result is sentinel


# ---------------------------------------------------------------------------
# TokenPassthroughMiddleware
# ---------------------------------------------------------------------------


class TestTokenPassthroughMiddleware:
    @pytest.fixture(autouse=True)
    def _clean_passthrough_token(self) -> Generator[None]:
        token = _passthrough_token.set(None)
        yield
        _passthrough_token.reset(token)

    @pytest.mark.anyio
    async def test_rejects_tool_call_without_token(self) -> None:
        middleware = TokenPassthroughMiddleware()
        ctx = _make_tool_context("get_schema")

        async def call_next(c: MiddlewareContext[Any]) -> ToolResult:
            msg = "should not reach here"
            raise AssertionError(msg)

        with pytest.raises(McpError, match="Authentication required"):
            await middleware.on_call_tool(ctx, call_next)

    @pytest.mark.anyio
    async def test_rejects_resource_read_without_token(self) -> None:
        middleware = TokenPassthroughMiddleware()
        ctx = _make_resource_context("infrahub://schema")

        async def call_next(c: MiddlewareContext[Any]) -> str:
            msg = "should not reach here"
            raise AssertionError(msg)

        with pytest.raises(McpError, match="Authentication required"):
            await middleware.on_read_resource(ctx, call_next)

    @pytest.mark.anyio
    async def test_allows_tool_call_with_token(self) -> None:
        middleware = TokenPassthroughMiddleware()
        ctx = _make_tool_context("get_schema")
        expected = ToolResult(content=[])

        async def call_next(c: MiddlewareContext[Any]) -> ToolResult:
            return expected

        set_passthrough_token("valid-token")
        result = await middleware.on_call_tool(ctx, call_next)
        assert result is expected

    @pytest.mark.anyio
    async def test_allows_resource_read_with_token(self) -> None:
        middleware = TokenPassthroughMiddleware()
        ctx = _make_resource_context("infrahub://schema")

        async def call_next(c: MiddlewareContext[Any]) -> str:
            return "data"

        set_passthrough_token("valid-token")
        result = await middleware.on_read_resource(ctx, call_next)
        assert result == "data"


# ---------------------------------------------------------------------------
# configure_middleware — token-passthrough mode
# ---------------------------------------------------------------------------


class TestConfigureMiddlewareTokenPassthrough:
    def test_token_passthrough_middleware_enabled(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig(auth_mode="token-passthrough")
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "TokenPassthroughMiddleware" in types

    def test_token_passthrough_middleware_not_in_none_mode(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig(auth_mode="none")
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "TokenPassthroughMiddleware" not in types


# ---------------------------------------------------------------------------
# InfrahubConnectionMiddleware
# ---------------------------------------------------------------------------


class TestInfrahubConnectionMiddleware:
    @pytest.mark.anyio
    async def test_catches_server_not_reachable_on_tool_call(self) -> None:
        middleware = InfrahubConnectionMiddleware()
        ctx = _make_tool_context("get_schema")

        async def call_next(c: MiddlewareContext[Any]) -> ToolResult:
            raise ServerNotReachableError(address="http://infrahub:8000")

        with pytest.raises(McpError, match="Infrahub is unreachable"):
            await middleware.on_call_tool(ctx, call_next)

    @pytest.mark.anyio
    async def test_catches_server_not_reachable_on_resource_read(self) -> None:
        middleware = InfrahubConnectionMiddleware()
        ctx = _make_resource_context("infrahub://schema")

        async def call_next(c: MiddlewareContext[Any]) -> str:
            raise ServerNotReachableError(address="http://infrahub:8000")

        with pytest.raises(McpError, match="Infrahub is unreachable"):
            await middleware.on_read_resource(ctx, call_next)

    @pytest.mark.anyio
    async def test_catches_server_not_responsive(self) -> None:
        middleware = InfrahubConnectionMiddleware()
        ctx = _make_tool_context("get_schema")

        async def call_next(c: MiddlewareContext[Any]) -> ToolResult:
            raise ServerNotResponsiveError(url="http://infrahub:8000/api/schema")

        with pytest.raises(McpError, match="Infrahub is not responding"):
            await middleware.on_call_tool(ctx, call_next)

    @pytest.mark.anyio
    async def test_catches_authentication_error(self) -> None:
        middleware = InfrahubConnectionMiddleware()
        ctx = _make_tool_context("get_schema")

        async def call_next(c: MiddlewareContext[Any]) -> ToolResult:
            raise AuthenticationError("Invalid API token")

        with pytest.raises(McpError, match="401 Unauthorized"):
            await middleware.on_call_tool(ctx, call_next)

    @pytest.mark.anyio
    async def test_catches_httpx_connect_error(self) -> None:
        import httpx  # noqa: PLC0415

        middleware = InfrahubConnectionMiddleware()
        ctx = _make_tool_context("get_schema")

        async def call_next(c: MiddlewareContext[Any]) -> ToolResult:
            raise httpx.ConnectError("Connection refused")

        with pytest.raises(McpError, match="Cannot connect to Infrahub"):
            await middleware.on_call_tool(ctx, call_next)

    @pytest.mark.anyio
    async def test_passes_through_on_success(self) -> None:
        middleware = InfrahubConnectionMiddleware()
        ctx = _make_tool_context("get_schema")
        expected = ToolResult(content=[])

        async def call_next(c: MiddlewareContext[Any]) -> ToolResult:
            return expected

        result = await middleware.on_call_tool(ctx, call_next)
        assert result is expected

    @pytest.mark.anyio
    async def test_does_not_catch_other_exceptions(self) -> None:
        middleware = InfrahubConnectionMiddleware()
        ctx = _make_tool_context("get_schema")

        async def call_next(c: MiddlewareContext[Any]) -> ToolResult:
            msg = "some other error"
            raise ValueError(msg)

        with pytest.raises(ValueError, match="some other error"):
            await middleware.on_call_tool(ctx, call_next)

    def test_always_in_middleware_stack(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []
        mock_mcp.add_middleware.side_effect = lambda mw: mock_mcp.middleware.append(mw)

        config = ServerConfig()
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "InfrahubConnectionMiddleware" in types


# ---------------------------------------------------------------------------
# StrictResponseLimitingMiddleware
# ---------------------------------------------------------------------------


class TestStrictResponseLimitingMiddleware:
    @pytest.mark.anyio
    async def test_passes_through_when_under_limit(self) -> None:
        middleware = StrictResponseLimitingMiddleware(max_size=10_000)
        ctx = _make_tool_context("get_nodes")
        expected = ToolResult(content=[TextContent(type="text", text="small")])

        async def call_next(c: MiddlewareContext[Any]) -> ToolResult:
            return expected

        result = await middleware.on_call_tool(ctx, call_next)
        assert result is expected

    @pytest.mark.anyio
    async def test_raises_tool_error_when_over_limit(self) -> None:
        middleware = StrictResponseLimitingMiddleware(max_size=200)
        ctx = _make_tool_context("get_nodes")
        big_text = "x" * 5_000
        oversized = ToolResult(content=[TextContent(type="text", text=big_text)])

        async def call_next(c: MiddlewareContext[Any]) -> ToolResult:
            return oversized

        with pytest.raises(ToolError) as excinfo:
            await middleware.on_call_tool(ctx, call_next)

        msg = str(excinfo.value)
        assert "get_nodes" in msg
        assert "Remediation:" in msg
        assert "filters" in msg
        assert "limit" in msg

    @pytest.mark.anyio
    async def test_respects_tools_allowlist(self) -> None:
        """When ``tools`` is set, untracked tools bypass the size check."""
        middleware = StrictResponseLimitingMiddleware(
            max_size=200,
            tools=["other_tool"],
        )
        ctx = _make_tool_context("get_nodes")
        big_text = "x" * 5_000
        oversized = ToolResult(content=[TextContent(type="text", text=big_text)])

        async def call_next(c: MiddlewareContext[Any]) -> ToolResult:
            return oversized

        result = await middleware.on_call_tool(ctx, call_next)
        assert result is oversized

    def test_registered_in_middleware_stack(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []
        mock_mcp.add_middleware.side_effect = lambda mw: mock_mcp.middleware.append(mw)

        config = ServerConfig()
        configure_middleware(mock_mcp, config)

        types = [type(m).__name__ for m in mock_mcp.middleware]
        assert "StrictResponseLimitingMiddleware" in types
        assert "ResponseLimitingMiddleware" not in [t for t in types if t != "StrictResponseLimitingMiddleware"]
