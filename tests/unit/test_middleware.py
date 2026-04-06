"""Tests for the Infrahub MCP middleware stack."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any
from unittest.mock import MagicMock

import mcp.types as mt
import pytest
from fastmcp.server.middleware.middleware import MiddlewareContext
from fastmcp.tools.base import ToolResult

import infrahub_mcp.middleware as middleware_module
from mcp import McpError

from infrahub_mcp.config import ServerConfig
from infrahub_mcp.middleware import (
    AuditMiddleware,
    MetricsMiddleware,
    OTelTracingMiddleware,
    ReadOnlyMiddleware,
    RequestIdMiddleware,
    WRITE_TAG,
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

    def __init__(self, name: str, *, tags: set[str] | None = None) -> None:
        self.name = name
        self.tags = tags or set()


def _make_tool(name: str, *, tags: set[str] | None = None) -> Any:
    """Create a minimal object with ``name`` and ``tags`` for testing."""
    return _FakeTool(name, tags=tags)


# ---------------------------------------------------------------------------
# RequestIdMiddleware
# ---------------------------------------------------------------------------


class TestRequestIdMiddleware:
    @pytest.mark.anyio
    async def test_injects_request_id_in_logs(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
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
    async def test_logs_error_status_on_failure(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
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
    async def test_blocks_known_write_tools_without_context(
        self, tool_name: str
    ) -> None:
        """Fallback name-based check blocks all known write tools."""
        middleware = ReadOnlyMiddleware()
        ctx = _make_tool_context(tool_name)

        async def call_next(c: MiddlewareContext[Any]) -> ToolResult:
            msg = "should not reach here"
            raise AssertionError(msg)

        with pytest.raises(McpError):
            await middleware.on_call_tool(ctx, call_next)


# ---------------------------------------------------------------------------
# AuditMiddleware
# ---------------------------------------------------------------------------


class TestAuditMiddleware:
    @pytest.mark.anyio
    async def test_logs_tool_call(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
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
    async def test_logs_resource_read(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
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
        import json

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


@pytest.fixture(autouse=True)
def _reset_middleware_globals() -> None:
    """Reset module-level middleware state between tests."""
    middleware_module._metrics = None  # noqa: SLF001
    middleware_module._error_handling = None  # noqa: SLF001
    middleware_module._caching_middleware = None  # noqa: SLF001


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

        config = ServerConfig(log_level_debug=True)
        configure_middleware(mock_mcp, config)

        error_mw = next(
            m
            for m in mock_mcp.middleware
            if type(m).__name__ == "ErrorHandlingMiddleware"
        )
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

    def test_auth_middleware_enabled(self) -> None:
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig(auth_scopes_write="infrahub:write,admin")
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

    def test_all_middleware_enabled(self) -> None:
        """Smoke test: enable all optional middleware at once."""
        mock_mcp = MagicMock()
        mock_mcp.middleware = []

        def side_effect(mw: Any) -> None:
            mock_mcp.middleware.append(mw)

        mock_mcp.add_middleware.side_effect = side_effect

        config = ServerConfig(
            read_only=True,
            log_level_debug=True,
            rate_limit_rps=10.0,
            rate_limit_burst=20,
            retry_max_attempts=3,
            cache_enabled=True,
            otel_enabled=True,
            dereference_schemas=True,
            ping_interval_ms=5000,
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

        rate_limiter = next(
            m for m in mock_mcp.middleware if type(m).__name__ == "RateLimitingMiddleware"
        )
        assert rate_limiter.burst_capacity == 20  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Module-level getters
# ---------------------------------------------------------------------------


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
