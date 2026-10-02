# 2. Middleware Stack Ordering

**Status:** Accepted
**Date:** 2026-04-21
**Author:** @bkohler

## Context

The Infrahub MCP server requires multiple cross-cutting concerns — observability, error handling, retry, rate limiting, caching, authentication, read-only enforcement, and audit logging. These must intercept every tool call and resource read in a predictable, debuggable order.

FastMCP provides a middleware composition pattern where middleware classes are added to the server and executed as an ordered chain. The question was: how to organize 17 middleware layers, and whether to compose them once at startup or rebuild per request.

## Decision

Compose a 17-layer middleware stack once at startup via a single `configure_middleware()` function in `middleware.py`. The stack is ordered outermost (first to run) to innermost (closest to tool execution):

1. `RequestIdMiddleware` — correlation ID
2. `MetricsMiddleware` — Prometheus counters
3. `OTelTracingMiddleware` — OpenTelemetry spans
4. `ErrorHandlingMiddleware` — exception translation
5. `InfrahubConnectionMiddleware` — SDK error handling
6. `RetryMiddleware` — transient failure retry
7. `RateLimitingMiddleware` — token-bucket throttling
8. `StructuredLoggingMiddleware` — JSON logs
9. `DetailedTimingMiddleware` — timing breakdown
10. `ResponseCachingMiddleware` — TTL-based cache
11. `DereferenceRefsMiddleware` — JSON Schema `$ref` resolution
12. `PingMiddleware` — HTTP keep-alive
13. `AuthMiddleware` — OIDC scope enforcement
14. `TokenPassthroughMiddleware` — credential presence
15. `ReadOnlyMiddleware` — write tool filtering
16. `AuditMiddleware` — write operation audit log
17. `ResponseLimitingMiddleware` — size control (innermost)

Each layer is conditionally activated based on `ServerConfig` flags. The stack is configuration-dependent, not request-dependent.

## Consequences

### Positive

- Observability wraps everything — request ID, metrics, and tracing capture the full lifecycle including errors and retries
- Error handling sits before retry, catching non-retryable failures early
- Single composition point makes the ordering explicit and debuggable
- Adding a new middleware means one insertion in `configure_middleware()`, nothing else

### Negative

- All 17 classes live in one file (`middleware.py`, ~800 lines) — large but intentionally centralized
- Ordering bugs are subtle — moving a layer can silently change behavior (for example, caching before auth would bypass auth)

### Neutral

- Auth sits after caching — FastMCP caching is key-based and auth-aware, so cached responses don't bypass auth
- ReadOnly sits after auth so permission checks happen before tool filtering

## Alternatives Considered

### Scatter middleware across modules

Each concern in its own file (for example, `auth_middleware.py`, `logging_middleware.py`). Rejected: impossible to see the full ordering in one place, hard to debug interaction between layers.

### Per-request middleware construction

Rebuild the stack on every request based on request properties. Rejected: the stack depends on server configuration (fixed at startup), not request properties. Per-request construction adds unnecessary overhead and complexity.
