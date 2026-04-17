"""Tests for the Infrahub MCP middleware stack.

This slice covers only ReadOnlyMiddleware. Follow-up PRs in the middleware
rollout append their own test classes here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import mcp.types as mt
import pytest
from fastmcp.server.middleware.middleware import MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp import McpError

from infrahub_mcp.middleware import WRITE_TAG, ReadOnlyMiddleware

if TYPE_CHECKING:
    from collections.abc import Sequence


def _make_tool_context(tool_name: str) -> MiddlewareContext[mt.CallToolRequestParams]:
    """Create a MiddlewareContext for a tool call."""
    params = mt.CallToolRequestParams(name=tool_name, arguments={})
    return MiddlewareContext(message=params, method="tools/call")


def _make_list_tools_context() -> MiddlewareContext[mt.ListToolsRequest]:
    """Create a MiddlewareContext for listing tools."""
    return MiddlewareContext(
        message=mt.ListToolsRequest(method="tools/list"),
        method="tools/list",
    )


class _FakeTool:
    """Lightweight stand-in for fastmcp Tool in middleware tests."""

    def __init__(self, name: str, *, tags: set[str] | None = None) -> None:
        self.name = name
        self.tags = tags or set()


def _make_tool(name: str, *, tags: set[str] | None = None) -> Any:
    return _FakeTool(name, tags=tags)


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

        async def call_next(c: MiddlewareContext[Any]) -> Sequence[Any]:
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
        all_tools = [_make_tool("write_report", tags={"reports", "generate"})]

        async def call_next(c: MiddlewareContext[Any]) -> Sequence[Any]:
            return all_tools

        ctx = _make_list_tools_context()
        result = await middleware.on_list_tools(ctx, call_next)
        assert len(result) == 1

    @pytest.mark.anyio
    async def test_blocks_write_tool_call_without_context(self) -> None:
        """Without fastmcp_context, falls back to hardcoded name allowlist."""
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
        """Fail-closed: any tool not in the read-only allowlist is blocked."""
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

    @pytest.mark.anyio
    async def test_tool_lookup_that_raises_falls_back_to_allowlist(self) -> None:
        """If fastmcp.get_tool() raises, fall through to the fail-closed allowlist.

        A malformed or stale tool name must not escape as an unhandled server
        error — the middleware should still make a policy decision.
        """

        class _RaisingFastMCP:
            async def get_tool(self, name: str) -> Any:
                msg = f"tool not found: {name}"
                raise RuntimeError(msg)

        class _FakeFastMCPContext:
            def __init__(self) -> None:
                self.fastmcp = _RaisingFastMCP()

        middleware = ReadOnlyMiddleware()
        params = mt.CallToolRequestParams(name="node_upsert", arguments={})
        ctx = MiddlewareContext(
            message=params,
            method="tools/call",
            fastmcp_context=_FakeFastMCPContext(),  # type: ignore[arg-type]
        )

        async def call_next(c: MiddlewareContext[Any]) -> ToolResult:
            msg = "should not reach here"
            raise AssertionError(msg)

        with pytest.raises(McpError, match="read-only mode"):
            await middleware.on_call_tool(ctx, call_next)
