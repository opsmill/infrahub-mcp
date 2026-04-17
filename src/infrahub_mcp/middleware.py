"""Middleware stack for the Infrahub MCP server.

Scaffold registered from ``server.py`` via :func:`configure_middleware`. Each
section below is populated incrementally by the follow-up PRs that make up
the middleware rollout (see ``specs/INFP-411.md``).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, override

from fastmcp.server.middleware.middleware import (
    CallNext,
    Middleware,
    MiddlewareContext,
)
from mcp import McpError
from mcp.types import ErrorData

if TYPE_CHECKING:
    from collections.abc import Sequence

    import mcp.types as mt
    from fastmcp import FastMCP
    from fastmcp.tools.base import Tool, ToolResult

    from infrahub_mcp.config import ServerConfig

logger = logging.getLogger("infrahub_mcp.middleware")

# Tag used on all write tools (node_upsert, node_delete, propose_changes, mutate_graphql).
# ReadOnlyMiddleware filters by this tag rather than hardcoding tool names,
# so any new write tool automatically gets blocked if tagged "write".
WRITE_TAG = "write"


# ---------------------------------------------------------------------------
# Safety — read-only enforcement
# ---------------------------------------------------------------------------


class ReadOnlyMiddleware(Middleware):
    """Enforce read-only mode at the middleware layer.

    Uses the ``"write"`` tag on tools to identify write operations. Any new
    tool tagged ``"write"`` is automatically blocked — no hardcoded tool name
    list required.

    Provides two layers of protection:

    1. **Tool hiding** — ``on_list_tools`` filters tools tagged ``"write"``
       from discovery so LLMs never see them.
    2. **Call rejection** — ``on_call_tool`` resolves the tool and blocks it
       if tagged ``"write"``, catching hardcoded tool names that bypass
       discovery.

    The fallback path (when ``fastmcp_context`` is unavailable) is
    **fail-closed**: only tools in a known read-only allowlist are permitted;
    any unknown tool is blocked.

    This is defense-in-depth on top of the ``mcp.mount()`` gating in
    ``server.py``, which hides write tools at registration time.
    """

    _KNOWN_READ_ONLY_TOOLS: frozenset[str] = frozenset(
        {
            "get_schema",
            "query_graphql",
            "get_nodes",
            "search_nodes",
        }
    )

    @override
    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        filtered = [t for t in tools if WRITE_TAG not in (t.tags or set())]
        hidden = len(tools) - len(filtered)
        if hidden:
            logger.debug("read_only_filter hidden_tools=%d", hidden)
        return filtered

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name = context.message.name

        is_write = False
        if context.fastmcp_context is not None:
            tool = await context.fastmcp_context.fastmcp.get_tool(tool_name)
            is_write = (
                WRITE_TAG in (tool.tags or set()) if tool is not None else tool_name not in self._KNOWN_READ_ONLY_TOOLS
            )
        else:
            is_write = tool_name not in self._KNOWN_READ_ONLY_TOOLS

        if is_write:
            logger.warning("read_only_blocked tool=%s", tool_name)
            raise McpError(
                ErrorData(
                    code=-32601,
                    message=(
                        f"Tool '{tool_name}' is not available in "
                        "read-only mode. Write operations are "
                        "disabled on this server."
                    ),
                )
            )
        return await call_next(context)


# ---------------------------------------------------------------------------
# Production hardening (rate limit, caching, retry, error handling)
# ---------------------------------------------------------------------------
# Populated by PR 4.


# ---------------------------------------------------------------------------
# Observability (request IDs, structured logging, timing, tracing, audit)
# ---------------------------------------------------------------------------
# Populated by PR 5.


# ---------------------------------------------------------------------------
# Compatibility (dereference $ref, ping keepalive)
# ---------------------------------------------------------------------------
# Populated by PR 6.


def configure_middleware(mcp: FastMCP, config: ServerConfig) -> None:
    """Register middleware on the FastMCP instance."""
    if config.read_only:
        mcp.add_middleware(ReadOnlyMiddleware())
