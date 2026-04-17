# INFP-411 / PR 5 — Observability (request IDs, structured logging, timing, OTel, Prometheus, audit, health)

**Parent spec:** [INFP-411.md](./INFP-411.md)
**Slice branch:** `feat/mw-observability` (off `feat/mw-auth`, merges to `stable` independently)
**Status:** Not started

## Product requirement

Maps to **INFP-411 requirement #7 (Health Check Endpoint)** plus additional instrumentation not called out in the Jira idea: request correlation IDs, structured logs, per-request timing, OpenTelemetry traces, Prometheus metrics, and structured audit logging.

The health check alone would be a small change; bundling it with observability keeps all "what is the server doing?" concerns in one review. Like PR 4, this exceeds the INFP-411 spec — call out in the PR body so Product can decide whether to defer.

## Customer problem

Operators deploying the MCP server in HTTP mode need the same signals they expect from any other production service: liveness/readiness probes, request latency histograms, error rates, and a per-request correlation ID for debugging. Without them, operating the MCP server feels like a black box and incidents are hard to triage.

## What ships in this PR

*TBD — fill in at PR open. Expected surface:*

- `RequestIdMiddleware` — injects a correlation ID into a `ContextVar` and all log records for the request
- `StructuredLoggingMiddleware` — JSON-formatted logs with request ID, tool name, user (when PR 3 is merged), latency
- `DetailedTimingMiddleware` — records per-tool latency histogram
- `OTelTracingMiddleware` — OpenTelemetry spans for every MCP request (tool calls, resource reads, prompt renders)
- `/metrics` endpoint — JSON by default, Prometheus exposition format when `INFRAHUB_MCP_PROMETHEUS_ENABLED=true`
- `/health` endpoint — liveness + readiness probe, verifies connectivity to Infrahub via `client.get_version()`
- `AuditMiddleware` — structured audit log of every tool/resource access (user-aware once PR 3 lands)
- `tests/unit/test_health.py` + observability-specific tests

## Configuration surface

| Env var | Default | Purpose |
|---|---|---|
| `INFRAHUB_MCP_OTEL_ENABLED` | `false` | Enable OpenTelemetry tracing |
| `INFRAHUB_MCP_PROMETHEUS_ENABLED` | `false` | Expose `/metrics` in Prometheus exposition format |
| `INFRAHUB_MCP_LOG_LEVEL` | `info` | Log level (`debug`, `info`, `warning`, `error`) |

All env vars above are already parsed into `ServerConfig` in PR 1.

## Validation

- Unit tests: `tests/unit/test_health.py`, observability slices in `test_middleware.py`
- Manual: start server, hit `/health` (expect 200 when Infrahub is reachable, 503 when unreachable). Hit `/metrics`, verify Prometheus format. Configure an OTel collector and verify spans arrive.

## Open questions / follow-ups

*TBD at PR open. The AuditMiddleware's user-aware behavior depends on PR 3 landing first — if PR 5 merges before PR 3, ship with anonymous audit logs and revisit.*

## Links

- PR: *(fill in when opened)*
- Jira: [INFP-411](https://opsmill.atlassian.net/browse/INFP-411)
