# 2. Middleware Stack Ordering

**Status:** Accepted
**Date:** 2026-04-21
**Author:** @bkohler
**Updated:** 2026-11-09 — layer order, class names and activation brought in line with `configure_middleware()` in `src/infrahub_mcp/middleware.py`

## Context

The Infrahub MCP server requires multiple cross-cutting concerns — observability, error handling, retry, rate limiting, caching, authentication, read-only enforcement, and audit logging. These must intercept every tool call and resource read in a predictable, debuggable order.

FastMCP provides a middleware composition pattern where middleware classes are added to the server and executed as an ordered chain. The question was: how to organize 17 middleware layers, and whether to compose them once at startup or rebuild per request.

## Decision

Compose a 17-layer middleware stack once at startup via a single `configure_middleware()` function in `middleware.py`. The stack is ordered outermost (first to run) to innermost (closest to tool execution):

1. `RequestIdMiddleware` — correlation ID
2. `MetricsMiddleware` — Prometheus counters
3. `OTelTracingMiddleware` — OpenTelemetry spans
4. `ToolResultErrorHandlingMiddleware` — exception translation
5. `InfrahubConnectionMiddleware` — SDK error handling
6. `SafeRetryMiddleware` — transient failure retry, skipping non-idempotent tool calls
7. `RateLimitingMiddleware` — token-bucket throttling
8. `StructuredLoggingMiddleware` — JSON logs
9. `DetailedTimingMiddleware` — timing breakdown
10. `AuthMiddleware` — OIDC scope enforcement
11. `TokenPassthroughMiddleware` — credential presence
12. `ReadOnlyMiddleware` — write tool filtering
13. `AuditMiddleware` — tool and resource access log
14. `ResponseCachingMiddleware` — TTL-based cache
15. `DereferenceRefsMiddleware` — JSON Schema `$ref` resolution
16. `PingMiddleware` — HTTP keep-alive
17. `StrictResponseLimitingMiddleware` — size control (innermost)

Eight layers are always registered: request ID, metrics, error handling, Infrahub connection, structured logging, detailed timing, audit and response limiting. The other nine are registered only when their `ServerConfig` flag enables them. The stack is configuration-dependent, not request-dependent.

## Consequences

### Positive

- Observability wraps everything — request ID, metrics, and tracing capture the full lifecycle including errors and retries
- Error handling sits before retry, catching non-retryable failures early
- Single composition point makes the ordering explicit and debuggable
- Adding a new middleware means one insertion in `configure_middleware()`, nothing else

### Negative

- The stack is composed in one file (`middleware.py`, ~900 lines): 10 of the 17 classes are defined there and 7 are imported from FastMCP — large but intentionally centralized
- Ordering bugs are subtle — moving a layer can silently change behavior (for example, caching before auth would bypass auth)

### Neutral

- Auth, passthrough, read-only and audit sit outside caching, so a cached response never skips the permission checks or the audit log
- ReadOnly sits after auth so permission checks happen before tool filtering

## Alternatives Considered

### Scatter middleware across modules

Each concern in its own file (for example, `auth_middleware.py`, `logging_middleware.py`). Rejected: impossible to see the full ordering in one place, hard to debug interaction between layers.

### Per-request middleware construction

Rebuild the stack on every request based on request properties. Rejected: the stack depends on server configuration (fixed at startup), not request properties. Per-request construction adds unnecessary overhead and complexity.
