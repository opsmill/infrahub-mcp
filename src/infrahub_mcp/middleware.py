"""Middleware stack for the Infrahub MCP server.

Composes FastMCP built-in middleware with Infrahub-specific interceptors
for structured logging, request auditing, error handling, and response
size control.

Usage in server.py::

    from infrahub_mcp.middleware import configure_middleware
    configure_middleware(mcp, config)
"""

from __future__ import annotations

import logging
import secrets
from typing import TYPE_CHECKING, Any, override

from fastmcp.server.middleware.error_handling import ErrorHandlingMiddleware
from fastmcp.server.middleware.logging import StructuredLoggingMiddleware
from fastmcp.server.middleware.middleware import (
    CallNext,
    Middleware,
    MiddlewareContext,
)
from fastmcp.server.middleware.response_limiting import (
    ResponseLimitingMiddleware,
)
from fastmcp.server.middleware.timing import DetailedTimingMiddleware
from mcp import McpError
from mcp.types import ErrorData

if TYPE_CHECKING:
    from collections.abc import Sequence

    import mcp.types as mt
    from fastmcp.tools.base import Tool, ToolResult

    from infrahub_mcp.config import ServerConfig

logger = logging.getLogger("infrahub_mcp.middleware")

# ---------------------------------------------------------------------------
# Infrahub-specific middleware
# ---------------------------------------------------------------------------

_WRITE_TOOLS: frozenset[str] = frozenset({"node_upsert", "node_delete", "propose_changes", "mutate_graphql"})


class RequestIdMiddleware(Middleware):
    """Inject a unique request ID into every request for traceability.

    The ID is logged at the start and end of processing so operators can
    correlate log lines across the middleware stack.
    """

    @override
    async def on_message(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        request_id = secrets.token_hex(8)
        method = context.method or "unknown"
        logger.info(
            "request_start request_id=%s method=%s",
            request_id,
            method,
        )
        try:
            result = await call_next(context)
            logger.info(
                "request_end request_id=%s method=%s status=ok",
                request_id,
                method,
            )
            return result
        except Exception:
            logger.warning(
                "request_end request_id=%s method=%s status=error",
                request_id,
                method,
            )
            raise


class ReadOnlyMiddleware(Middleware):
    """Enforce read-only mode at the middleware layer.

    Provides two layers of protection:

    1. **Tool hiding** — ``on_list_tools`` filters write tools from
       discovery responses so LLMs never see them.
    2. **Call rejection** — ``on_call_tool`` blocks any call to a write
       tool that bypasses discovery (e.g. a hardcoded tool name).

    This is defense-in-depth on top of the ``mcp.mount()`` gating in
    ``server.py``, which hides write tools at registration time.
    """

    @override
    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        filtered = [t for t in tools if t.name not in _WRITE_TOOLS]
        hidden = len(tools) - len(filtered)
        if hidden:
            logger.debug(
                "read_only_filter hidden_tools=%d",
                hidden,
            )
        return filtered

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name = context.message.name
        if tool_name in _WRITE_TOOLS:
            logger.warning(
                "read_only_blocked tool=%s",
                tool_name,
            )
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


class AuditMiddleware(Middleware):
    """Log every tool call and resource read with structured audit fields.

    Produces log lines that are easy to parse with log aggregation tools
    (ELK, Loki, Datadog) for usage analytics and incident investigation.
    """

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name = context.message.name
        is_write = tool_name in _WRITE_TOOLS
        logger.info(
            "tool_call tool=%s write=%s",
            tool_name,
            is_write,
        )
        return await call_next(context)

    @override
    async def on_read_resource(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        uri = getattr(context.message, "uri", "unknown")
        logger.info("resource_read uri=%s", uri)
        return await call_next(context)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_MAX_RESPONSE_BYTES = 500_000  # 500 KB — generous for TOON-encoded data


def configure_middleware(mcp: Any, config: ServerConfig) -> None:
    """Register the full middleware stack on the FastMCP server.

    Middleware executes in registration order (first registered = outermost).
    The stack is ordered for optimal observability and safety:

    1. **RequestIdMiddleware** — assigns a correlation ID (outermost)
    2. **ErrorHandlingMiddleware** — catches unhandled exceptions
    3. **StructuredLoggingMiddleware** — JSON logs with token estimates
    4. **DetailedTimingMiddleware** — per-operation timing breakdown
    5. **ReadOnlyMiddleware** — blocks write tools (conditional)
    6. **AuditMiddleware** — structured audit trail
    7. **ResponseLimitingMiddleware** — truncates oversized responses
    """
    # 1. Request ID correlation — outermost wrapper
    mcp.add_middleware(RequestIdMiddleware())

    # 2. Error handling — catches everything below
    mcp.add_middleware(
        ErrorHandlingMiddleware(
            logger=logging.getLogger("infrahub_mcp.errors"),
            include_traceback=config.log_level_debug,
            transform_errors=True,
        )
    )

    # 3. Structured logging — JSON log lines with token estimates
    mcp.add_middleware(
        StructuredLoggingMiddleware(
            logger=logging.getLogger("infrahub_mcp.requests"),
            log_level=logging.INFO,
            include_payload_length=True,
            estimate_payload_tokens=True,
        )
    )

    # 4. Detailed timing — per-operation breakdown
    mcp.add_middleware(
        DetailedTimingMiddleware(
            logger=logging.getLogger("infrahub_mcp.timing"),
        )
    )

    # 5. Read-only enforcement — defense-in-depth (conditional)
    if config.read_only:
        mcp.add_middleware(ReadOnlyMiddleware())
        logger.info("read_only_mode enabled=true")

    # 6. Audit trail — structured tool/resource access log
    mcp.add_middleware(AuditMiddleware())

    # 7. Response size limiting — innermost
    mcp.add_middleware(
        ResponseLimitingMiddleware(
            max_size=_MAX_RESPONSE_BYTES,
        )
    )

    logger.info(
        "middleware_configured count=%d read_only=%s",
        len(mcp.middleware),
        config.read_only,
    )
