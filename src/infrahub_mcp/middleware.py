"""Middleware stack for the Infrahub MCP server.

Composes FastMCP built-in middleware with Infrahub-specific interceptors
for structured logging, request auditing, error handling, response
size control, and observability.

Usage in server.py::

    from infrahub_mcp.middleware import configure_middleware
    configure_middleware(mcp, config)
"""

from __future__ import annotations

import logging
import secrets
import time
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

# Tag used on all write tools (node_upsert, node_delete, propose_changes, mutate_graphql).
# The ReadOnlyMiddleware filters by this tag rather than hardcoding tool names,
# so any new write tool automatically gets blocked if tagged "write".
WRITE_TAG = "write"


# ---------------------------------------------------------------------------
# Request correlation
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Read-only enforcement
# ---------------------------------------------------------------------------


class ReadOnlyMiddleware(Middleware):
    """Enforce read-only mode at the middleware layer.

    Uses the ``"write"`` tag on tools to identify write operations.
    Any new tool tagged ``"write"`` is automatically blocked — no hardcoded
    tool name list required.

    Provides two layers of protection:

    1. **Tool hiding** — ``on_list_tools`` filters tools tagged ``"write"``
       from discovery so LLMs never see them.
    2. **Call rejection** — ``on_call_tool`` resolves the tool and blocks it
       if tagged ``"write"``, catching hardcoded tool names that bypass discovery.

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

        # Resolve the tool to check its tags dynamically.
        # Fall back to name-based check if resolution is unavailable.
        is_write = False
        if context.fastmcp_context is not None:
            tool = await context.fastmcp_context.fastmcp.get_tool(
                tool_name
            )
            if tool is not None:
                is_write = WRITE_TAG in (tool.tags or set())
        else:
            # Defensive: without context, deny known write tools by name
            is_write = tool_name in {
                "node_upsert",
                "node_delete",
                "propose_changes",
                "mutate_graphql",
            }

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
# Audit trail
# ---------------------------------------------------------------------------


class AuditMiddleware(Middleware):
    """Log every tool call and resource read with structured audit fields.

    Produces log lines parseable by log aggregation tools (ELK, Loki,
    Datadog) for usage analytics and incident investigation.
    """

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name = context.message.name
        logger.info("tool_call tool=%s", tool_name)
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
# Metrics collection
# ---------------------------------------------------------------------------


class MetricsMiddleware(Middleware):
    """Collect request counts and latency for the ``/metrics`` endpoint.

    Tracks per-method request counts, error counts, and cumulative
    latency. Designed for scraping by Prometheus or similar.
    """

    def __init__(self) -> None:
        self._requests: dict[str, int] = {}
        self._errors: dict[str, int] = {}
        self._latency_ms: dict[str, float] = {}

    @override
    async def on_message(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        method = context.method or "unknown"
        self._requests[method] = self._requests.get(method, 0) + 1

        start = time.perf_counter()
        try:
            result = await call_next(context)
            elapsed = (time.perf_counter() - start) * 1000
            self._latency_ms[method] = (
                self._latency_ms.get(method, 0.0) + elapsed
            )
            return result
        except Exception:
            self._errors[method] = self._errors.get(method, 0) + 1
            raise

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable metrics snapshot."""
        return {
            "requests": dict(self._requests),
            "errors": dict(self._errors),
            "latency_ms": {
                k: round(v, 2) for k, v in self._latency_ms.items()
            },
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_MAX_RESPONSE_BYTES = 500_000  # 500 KB — generous for TOON-encoded data

# Module-level reference so server.py can access metrics from the route handler.
_metrics: MetricsMiddleware | None = None


def get_metrics() -> MetricsMiddleware | None:
    """Return the active MetricsMiddleware instance, if configured."""
    return _metrics


def configure_middleware(mcp: Any, config: ServerConfig) -> None:
    """Register the full middleware stack on the FastMCP server.

    Middleware executes in registration order (first registered = outermost).
    The stack is ordered for optimal observability and safety:

    1. **RequestIdMiddleware** — correlation ID (outermost)
    2. **MetricsMiddleware** — request/error/latency counters
    3. **ErrorHandlingMiddleware** — exception → MCP error mapping
    4. **StructuredLoggingMiddleware** — JSON logs with token estimates
    5. **DetailedTimingMiddleware** — per-operation timing breakdown
    6. **ReadOnlyMiddleware** — tag-based write tool blocking (conditional)
    7. **AuditMiddleware** — structured audit trail
    8. **ResponseLimitingMiddleware** — truncates oversized responses
    """
    global _metrics  # noqa: PLW0603

    # 1. Request ID correlation — outermost wrapper
    mcp.add_middleware(RequestIdMiddleware())

    # 2. Metrics — counts and latency for /metrics endpoint
    _metrics = MetricsMiddleware()
    mcp.add_middleware(_metrics)

    # 3. Error handling — catches everything below
    mcp.add_middleware(
        ErrorHandlingMiddleware(
            logger=logging.getLogger("infrahub_mcp.errors"),
            include_traceback=config.log_level_debug,
            transform_errors=True,
        )
    )

    # 4. Structured logging — JSON log lines with token estimates
    mcp.add_middleware(
        StructuredLoggingMiddleware(
            logger=logging.getLogger("infrahub_mcp.requests"),
            log_level=logging.INFO,
            include_payload_length=True,
            estimate_payload_tokens=True,
        )
    )

    # 5. Detailed timing — per-operation breakdown
    mcp.add_middleware(
        DetailedTimingMiddleware(
            logger=logging.getLogger("infrahub_mcp.timing"),
        )
    )

    # 6. Read-only enforcement — tag-based, defense-in-depth (conditional)
    if config.read_only:
        mcp.add_middleware(ReadOnlyMiddleware())
        logger.info("read_only_mode enabled=true")

    # 7. Audit trail — structured tool/resource access log
    mcp.add_middleware(AuditMiddleware())

    # 8. Response size limiting — innermost
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
