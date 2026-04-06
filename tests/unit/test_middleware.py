"""Tests for the Infrahub MCP middleware stack."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

import mcp.types as mt
import pytest
from fastmcp.server.middleware.middleware import MiddlewareContext
from fastmcp.tools.base import ToolResult

from infrahub_mcp.config import ServerConfig
from infrahub_mcp.middleware import (
    AuditMiddleware,
    MetricsMiddleware,
    ReadOnlyMiddleware,
    RequestIdMiddleware,
    WRITE_TAG,
    configure_middleware,
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

        from mcp import McpError

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

        from mcp import McpError

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


# ---------------------------------------------------------------------------
# configure_middleware
# ---------------------------------------------------------------------------


class TestConfigureMiddleware:
    def test_registers_middleware_read_write_mode(self) -> None:
        from unittest.mock import MagicMock

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
        from unittest.mock import MagicMock

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
        from unittest.mock import MagicMock

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
