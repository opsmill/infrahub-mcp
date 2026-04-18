"""Middleware stack for the Infrahub MCP server.

Composes FastMCP built-in middleware with Infrahub-specific interceptors
for structured logging, request auditing, error handling, response
size control, rate limiting, caching, retries, and observability.

Usage in server.py::

    from infrahub_mcp.middleware import configure_middleware
    configure_middleware(mcp, config)
"""

from __future__ import annotations

import contextvars
import logging
import secrets
import time
from typing import TYPE_CHECKING, Any, override

import pydantic_core
from fastmcp.exceptions import ToolError
from fastmcp.server.auth import restrict_tag
from fastmcp.server.middleware.authorization import AuthMiddleware
from fastmcp.server.middleware.caching import (
    CallToolSettings,
    ListPromptsSettings,
    ListResourcesSettings,
    ListToolsSettings,
    ReadResourceSettings,
    ResponseCachingMiddleware,
)
from fastmcp.server.middleware.dereference import DereferenceRefsMiddleware
from fastmcp.server.middleware.error_handling import (
    ErrorHandlingMiddleware,
    RetryMiddleware,
)
from fastmcp.server.middleware.logging import StructuredLoggingMiddleware
from fastmcp.server.middleware.middleware import (
    CallNext,
    Middleware,
    MiddlewareContext,
)
from fastmcp.server.middleware.ping import PingMiddleware
from fastmcp.server.middleware.rate_limiting import RateLimitingMiddleware
from fastmcp.server.middleware.response_limiting import (
    ResponseLimitingMiddleware,
)
from fastmcp.server.middleware.timing import DetailedTimingMiddleware
from infrahub_sdk.exceptions import AuthenticationError, ServerNotReachableError, ServerNotResponsiveError
from mcp import McpError
from mcp.types import ErrorData

from infrahub_mcp.auth import get_passthrough_token, get_user_from_token
from infrahub_mcp.constants import AUTH_MODE_OIDC, AUTH_MODE_TOKEN_PASSTHROUGH

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

# ContextVar for propagating the request ID to downstream middleware and log filters.
current_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_request_id", default=None)


# ---------------------------------------------------------------------------
# Request correlation
# ---------------------------------------------------------------------------


class RequestIdMiddleware(Middleware):
    """Inject a unique request ID into every request for traceability.

    The ID is stored in the ``current_request_id`` context variable so that
    downstream middleware, tool handlers, and log filters can include it
    for correlation.  It is also logged at the start and end of processing.
    """

    @override
    async def on_message(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        request_id = secrets.token_hex(8)
        token = current_request_id.set(request_id)
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
        finally:
            current_request_id.reset(token)


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

    The fallback path (when ``fastmcp_context`` is unavailable) is
    **fail-closed**: only tools in a known read-only allowlist are
    permitted; any unknown tool is blocked.

    This is defense-in-depth on top of the ``mcp.mount()`` gating in
    ``server.py``, which hides write tools at registration time.
    """

    # Known read-only tools used as an allowlist when tag-based resolution
    # is unavailable (fastmcp_context is None).  Fail-closed: any tool NOT
    # in this set is blocked.
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

        # Resolve the tool to check its tags dynamically.
        # Fall back to name-based check if resolution is unavailable.
        is_write = False
        if context.fastmcp_context is not None:
            tool = await context.fastmcp_context.fastmcp.get_tool(tool_name)
            is_write = (
                WRITE_TAG in (tool.tags or set()) if tool is not None else tool_name not in self._KNOWN_READ_ONLY_TOOLS
            )
        else:
            # Fail-closed: without context, only allow known read-only tools
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
# Token passthrough — fail-closed gate
# ---------------------------------------------------------------------------


class TokenPassthroughMiddleware(Middleware):
    """Fail-closed gate for token-passthrough auth mode.

    Rejects tool calls and resource reads when no passthrough token is set
    in the current request context.  The token itself is extracted by the
    ASGI-level ``_TokenPassthroughASGI`` middleware and stored in a
    ``ContextVar``; this middleware just enforces its presence.
    """

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        if get_passthrough_token() is None:
            raise McpError(
                ErrorData(
                    code=-32001,
                    message="Authentication required: no Infrahub API token in request header.",
                )
            )
        return await call_next(context)

    @override
    async def on_read_resource(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        if get_passthrough_token() is None:
            raise McpError(
                ErrorData(
                    code=-32001,
                    message="Authentication required: no Infrahub API token in request header.",
                )
            )
        return await call_next(context)


# ---------------------------------------------------------------------------
# Infrahub connection errors — friendly messages
# ---------------------------------------------------------------------------


class InfrahubConnectionMiddleware(Middleware):
    """Catch Infrahub SDK connection errors and return clean MCP errors.

    Converts ``ServerNotReachableError``, ``ServerNotResponsiveError``, and
    ``AuthenticationError`` into actionable ``McpError`` messages instead of
    leaking raw stack traces to the client.
    """

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        return await self._wrap(call_next, context)

    @override
    async def on_read_resource(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        return await self._wrap(call_next, context)

    @staticmethod
    async def _wrap(call_next: CallNext[Any, Any], context: MiddlewareContext[Any]) -> Any:
        try:
            return await call_next(context)
        except ServerNotReachableError as exc:
            raise McpError(
                ErrorData(code=-32002, message=f"Infrahub is unreachable at {exc}. Check that the instance is running.")
            ) from exc
        except ServerNotResponsiveError as exc:
            raise McpError(ErrorData(code=-32002, message=f"Infrahub is not responding: {exc}")) from exc
        except AuthenticationError as exc:
            raise McpError(ErrorData(code=-32001, message=f"Infrahub authentication failed: {exc}")) from exc


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


class AuditMiddleware(Middleware):
    """Log every tool call and resource read with structured audit fields.

    Produces log lines parseable by log aggregation tools (ELK, Loki,
    Datadog) for usage analytics and incident investigation.
    Includes authenticated user identity when available (OIDC mode).
    """

    def __init__(self, *, user_claim: str | None = None) -> None:
        self._user_claim = user_claim

    def _get_user(self) -> str:
        if self._user_claim is not None:
            return get_user_from_token(claim=self._user_claim)
        return "anonymous"

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name = context.message.name
        user = self._get_user()
        logger.info("tool_call tool=%s user=%s", tool_name, user)
        return await call_next(context)

    @override
    async def on_read_resource(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        uri = getattr(context.message, "uri", "unknown")
        user = self._get_user()
        logger.info("resource_read uri=%s user=%s", uri, user)
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
            return await call_next(context)
        except Exception:
            self._errors[method] = self._errors.get(method, 0) + 1
            raise
        finally:
            elapsed = (time.perf_counter() - start) * 1000
            self._latency_ms[method] = self._latency_ms.get(method, 0.0) + elapsed

    def snapshot(self) -> dict[str, Any]:
        """Return a JSON-serializable metrics snapshot."""
        return {
            "requests": dict(self._requests),
            "errors": dict(self._errors),
            "latency_ms": {k: round(v, 2) for k, v in self._latency_ms.items()},
        }

    def prometheus_text(self) -> str:
        """Render metrics in Prometheus exposition text format.

        Produces HELP/TYPE declarations and metric lines for:
        - ``infrahub_mcp_requests_total`` (counter)
        - ``infrahub_mcp_errors_total`` (counter)
        - ``infrahub_mcp_latency_ms_total`` (counter)
        """
        lines: list[str] = []

        lines.extend(
            (
                "# HELP infrahub_mcp_requests_total Total MCP requests by method.",
                "# TYPE infrahub_mcp_requests_total counter",
            )
        )
        for method, count in sorted(self._requests.items()):
            lines.append(f'infrahub_mcp_requests_total{{method="{method}"}} {count}')

        lines.extend(
            (
                "# HELP infrahub_mcp_errors_total Total MCP errors by method.",
                "# TYPE infrahub_mcp_errors_total counter",
            )
        )
        for method, count in sorted(self._errors.items()):
            lines.append(f'infrahub_mcp_errors_total{{method="{method}"}} {count}')

        lines.extend(
            (
                "# HELP infrahub_mcp_latency_ms_total Cumulative latency in milliseconds by method.",
                "# TYPE infrahub_mcp_latency_ms_total counter",
            )
        )
        for method, ms in sorted(self._latency_ms.items()):
            lines.append(f'infrahub_mcp_latency_ms_total{{method="{method}"}} {ms:.2f}')

        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# OpenTelemetry tracing
# ---------------------------------------------------------------------------


class OTelTracingMiddleware(Middleware):
    """Add OpenTelemetry spans around every MCP request.

    Creates a span named ``mcp.<method>`` for each request, recording
    the method, status, and any error details. Requires the
    ``opentelemetry-api`` package to be installed; degrades gracefully
    to a no-op if the package is unavailable.
    """

    def __init__(self, tracer_name: str = "infrahub_mcp") -> None:
        self._tracer: Any = None
        self._trace_mod: Any = None
        self._enabled = False
        try:
            import opentelemetry.trace as _trace  # noqa: PLC0415

            self._tracer = _trace.get_tracer(tracer_name)
            self._trace_mod = _trace
            self._enabled = True
        except ImportError:
            logger.warning("opentelemetry not installed; OTelTracingMiddleware disabled")

    @override
    async def on_message(
        self,
        context: MiddlewareContext[Any],
        call_next: CallNext[Any, Any],
    ) -> Any:
        if not self._enabled or self._tracer is None or self._trace_mod is None:
            return await call_next(context)

        method = context.method or "unknown"
        with self._tracer.start_as_current_span(f"mcp.{method}") as span:
            span.set_attribute("mcp.method", method)
            try:
                result = await call_next(context)
                span.set_attribute("mcp.status", "ok")
                return result
            except Exception as exc:
                span.set_attribute("mcp.status", "error")
                span.set_attribute("mcp.error.type", type(exc).__name__)
                span.record_exception(exc)
                span.set_status(self._trace_mod.StatusCode.ERROR, str(exc))
                raise


# ---------------------------------------------------------------------------
# Idempotency-aware retry
# ---------------------------------------------------------------------------


class SafeRetryMiddleware(RetryMiddleware):
    """Retry middleware that only retries safe tool calls.

    Extends FastMCP's ``RetryMiddleware`` with an ``on_call_tool`` override
    that checks ``ToolAnnotations.idempotentHint`` or ``readOnlyHint`` before
    retrying.  Non-safe tool calls (e.g. ``node_upsert`` without an id) are
    passed through without retries to avoid duplicate side effects.

    Other MCP methods (resource reads, prompt gets, list operations) are
    always safe to retry and use the parent class behavior.
    """

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        # Check if the tool is marked idempotent before applying retries
        tool = None
        if context.fastmcp_context is not None:
            tool = await context.fastmcp_context.fastmcp.get_tool(context.message.name)

        is_safe_to_retry = False
        if tool is not None and tool.annotations is not None:
            is_safe_to_retry = bool(tool.annotations.idempotentHint or tool.annotations.readOnlyHint)

        if not is_safe_to_retry:
            # Skip retry logic — call through directly
            return await call_next(context)

        # Delegate to parent retry logic
        return await super().on_call_tool(context, call_next)


# ---------------------------------------------------------------------------
# Strict response limiting — raise instead of truncating
# ---------------------------------------------------------------------------


class StrictResponseLimitingMiddleware(ResponseLimitingMiddleware):
    """Response limiter that raises ``ToolError`` instead of silently truncating.

    FastMCP's built-in ``ResponseLimitingMiddleware`` truncates oversized tool
    responses and appends a warning suffix.  An agent consuming that output has
    no programmatic signal that data was lost — it just sees a partial payload
    ending in ``[Response truncated due to size limit]`` mid-TOON row.

    This variant raises a ``ToolError`` with an actionable remediation instead,
    keeping the agent in its self-correction loop (tighten ``filters``, drop
    ``limit``, narrow ``include_attributes``) rather than guessing at truncated
    data.
    """

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        result = await call_next(context)

        if self.tools is not None and context.message.name not in self.tools:
            return result

        serialized = pydantic_core.to_json(result, fallback=str)
        if len(serialized) <= self.max_size:
            return result

        tool_name = context.message.name
        logger.warning(
            "tool=%r response_over_limit size=%d max=%d",
            tool_name,
            len(serialized),
            self.max_size,
        )
        raise ToolError(
            f"Response from {tool_name!r} is {len(serialized)} bytes, "
            f"over the {self.max_size}-byte limit.\n"
            "Remediation: narrow `filters`, lower `limit`, or drop "
            "`include_attributes` to reduce the payload. "
            "Check `infrahub://schema/{kind}` for available filters."
        )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_MAX_RESPONSE_BYTES = 500_000  # 500 KB — generous for TOON-encoded data

# Module-level references so server.py can access middleware instances from route handlers.
_metrics: MetricsMiddleware | None = None
_error_handling: ErrorHandlingMiddleware | None = None
_caching_middleware: Any | None = None  # ResponseCachingMiddleware (optional)


def get_metrics() -> MetricsMiddleware | None:
    """Return the active MetricsMiddleware instance, if configured."""
    return _metrics


def get_error_handling() -> ErrorHandlingMiddleware | None:
    """Return the active ErrorHandlingMiddleware instance, if configured."""
    return _error_handling


def get_caching_middleware() -> Any | None:
    """Return the active ResponseCachingMiddleware instance, if configured."""
    return _caching_middleware


def configure_middleware(mcp: Any, config: ServerConfig) -> None:
    """Register the full middleware stack on the FastMCP server.

    Middleware executes in registration order (first registered = outermost).
    The stack is ordered for optimal observability and safety:

    - **RequestIdMiddleware** — correlation ID (outermost)
    - **MetricsMiddleware** — request/error/latency counters
    - **OTelTracingMiddleware** — OpenTelemetry spans (conditional)
    - **ErrorHandlingMiddleware** — exception → MCP error mapping
    - **InfrahubConnectionMiddleware** — friendly Infrahub SDK error messages
    - **RetryMiddleware** — exponential backoff for transient failures (conditional)
    - **RateLimitingMiddleware** — token bucket rate limiting (conditional)
    - **StructuredLoggingMiddleware** — JSON logs with token estimates
    - **DetailedTimingMiddleware** — per-operation timing breakdown
    - **AuthMiddleware** — scope-based authorization for HTTP transport (conditional)
    - **TokenPassthroughMiddleware** — fail-closed gate for token-passthrough mode (conditional)
    - **ReadOnlyMiddleware** — tag-based write tool blocking (conditional)
    - **AuditMiddleware** — structured audit trail
    - **ResponseCachingMiddleware** — TTL-based response caching (conditional)
    - **DereferenceRefsMiddleware** — inline $ref in JSON schemas (conditional)
    - **PingMiddleware** — periodic keepalive pings for HTTP sessions (conditional)
    - **StrictResponseLimitingMiddleware** — rejects oversized responses with
      a ``ToolError`` + remediation hint (innermost)
    """
    global _metrics, _error_handling, _caching_middleware  # noqa: PLW0603

    # Reset module-level references so reconfiguration is clean
    _caching_middleware = None

    # Request ID correlation — outermost wrapper
    mcp.add_middleware(RequestIdMiddleware())

    # Metrics — counts and latency for /metrics endpoint
    _metrics = MetricsMiddleware()
    mcp.add_middleware(_metrics)

    # OpenTelemetry tracing — spans for every request (conditional)
    if config.otel_enabled:
        mcp.add_middleware(OTelTracingMiddleware())
        logger.info("otel_tracing enabled=true")

    # Error handling — catches everything below
    _error_handling = ErrorHandlingMiddleware(
        logger=logging.getLogger("infrahub_mcp.errors"),
        include_traceback=config.log_level_debug,
        transform_errors=True,
    )
    mcp.add_middleware(_error_handling)

    # Infrahub connection errors — friendly messages instead of raw stack traces
    mcp.add_middleware(InfrahubConnectionMiddleware())

    # Retry — exponential backoff for transient failures (conditional)
    # Uses SafeRetryMiddleware to skip retries for non-idempotent tool calls.
    if config.retry_max_attempts > 0:
        mcp.add_middleware(
            SafeRetryMiddleware(
                max_retries=config.retry_max_attempts,
                base_delay=config.retry_base_delay,
                retry_exceptions=(ConnectionError, TimeoutError, OSError),
                logger=logging.getLogger("infrahub_mcp.retry"),
            )
        )
        logger.info(
            "retry_middleware enabled=true max_retries=%d base_delay=%.1f",
            config.retry_max_attempts,
            config.retry_base_delay,
        )

    # Rate limiting — token bucket (conditional)
    if config.rate_limit_rps > 0:
        burst = config.rate_limit_burst if config.rate_limit_burst > 0 else int(config.rate_limit_rps * 2)
        mcp.add_middleware(
            RateLimitingMiddleware(
                max_requests_per_second=config.rate_limit_rps,
                burst_capacity=burst,
                global_limit=True,
            )
        )
        logger.info(
            "rate_limiting enabled=true rps=%.1f burst=%d",
            config.rate_limit_rps,
            burst,
        )

    # Structured logging — JSON log lines with token estimates
    mcp.add_middleware(
        StructuredLoggingMiddleware(
            logger=logging.getLogger("infrahub_mcp.requests"),
            log_level=logging.INFO,
            include_payload_length=True,
            estimate_payload_tokens=True,
        )
    )

    # Detailed timing — per-operation breakdown
    mcp.add_middleware(
        DetailedTimingMiddleware(
            logger=logging.getLogger("infrahub_mcp.timing"),
        )
    )

    # Auth middleware — scope-based authorization for OIDC transport (conditional)
    # Only enabled in OIDC mode where an auth provider supplies tokens with scopes.
    # In none mode (incl. stdio): no token provider exists, so scope checks are skipped.
    if config.auth_mode == AUTH_MODE_OIDC:
        scopes_raw = config.auth_scopes_write or "write"
        scopes = [s.strip() for s in scopes_raw.split(",") if s.strip()]
        mcp.add_middleware(AuthMiddleware(auth=restrict_tag(WRITE_TAG, scopes=scopes)))
        logger.info(
            "auth_middleware enabled=true auth_mode=%s write_scopes=%s",
            config.auth_mode,
            scopes,
        )

    # Token passthrough — fail-closed gate (conditional)
    if config.auth_mode == AUTH_MODE_TOKEN_PASSTHROUGH:
        mcp.add_middleware(TokenPassthroughMiddleware())
        logger.info("token_passthrough_middleware enabled=true")

    # Read-only enforcement — tag-based, defense-in-depth (conditional)
    if config.read_only:
        mcp.add_middleware(ReadOnlyMiddleware())
        logger.info("read_only_mode enabled=true")

    # Audit trail — structured tool/resource access log
    audit_claim = config.oidc_user_claim if config.auth_mode == AUTH_MODE_OIDC else None
    mcp.add_middleware(AuditMiddleware(user_claim=audit_claim))

    # Response caching — TTL-based for schema/list operations (conditional)
    if config.cache_enabled:
        _caching_middleware = ResponseCachingMiddleware(
            list_tools_settings=ListToolsSettings(ttl=config.cache_list_ttl),
            list_resources_settings=ListResourcesSettings(ttl=config.cache_list_ttl),
            list_prompts_settings=ListPromptsSettings(ttl=config.cache_list_ttl),
            read_resource_settings=ReadResourceSettings(ttl=config.cache_read_ttl),
            call_tool_settings=CallToolSettings(
                ttl=config.cache_read_ttl,
                included_tools=["get_schema"],
            ),
        )
        mcp.add_middleware(_caching_middleware)
        logger.info(
            "response_caching enabled=true list_ttl=%d read_ttl=%d",
            config.cache_list_ttl,
            config.cache_read_ttl,
        )

    # Dereference $ref in JSON schemas for client compatibility (conditional)
    if config.dereference_schemas:
        mcp.add_middleware(DereferenceRefsMiddleware())
        logger.info("dereference_schemas enabled=true")

    # Ping — periodic keepalive for HTTP sessions (conditional)
    if config.ping_interval_ms > 0:
        mcp.add_middleware(PingMiddleware(interval_ms=config.ping_interval_ms))
        logger.info("ping_middleware enabled=true interval_ms=%d", config.ping_interval_ms)

    # Response size limiting — innermost
    # StrictResponseLimitingMiddleware raises ToolError with a remediation
    # hint instead of silently truncating, so agents can self-correct.
    mcp.add_middleware(
        StrictResponseLimitingMiddleware(
            max_size=_MAX_RESPONSE_BYTES,
        )
    )

    logger.info(
        "middleware_configured count=%d read_only=%s",
        len(mcp.middleware),
        config.read_only,
    )
