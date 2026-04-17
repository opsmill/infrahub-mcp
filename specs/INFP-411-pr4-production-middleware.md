# INFP-411 / PR 4 — Production middleware (rate limiting, caching, retries, error handling)

**Parent spec:** [INFP-411.md](./INFP-411.md)
**Slice branch:** `feat/mw-prod` (off `feat/mw-auth`, merges to `stable` independently)
**Status:** Not started

## Product requirement

Exceeds the INFP-411 spec. This slice adds hardening (rate limiting, response caching, retries, centralized error handling) that isn't called out as a requirement but is needed for multi-tenant HTTP deployments to behave predictably under load and transient Infrahub failures.

Called out here so Product knows the slice exists and can decide whether it belongs in Phase 2 or a later phase. Recommendation: include in Phase 2 — the same deployments that need OIDC also need rate limiting.

## Customer problem

Without rate limiting, a misconfigured agent can exhaust Infrahub's request budget. Without caching, schema/list operations hammer Infrahub on every MCP list-tools call. Without retry, transient connection hiccups surface as agent-visible errors. These aren't theoretical — every production MCP deployment hits them.

## What ships in this PR

*TBD — fill in at PR open. Expected surface:*

- `RateLimitingMiddleware` — token-bucket with configurable RPS + burst
- `ResponseCachingMiddleware` — TTL-based caching for schema / list operations
- `RetryMiddleware` — exponential backoff for transient Infrahub failures
- `ErrorHandlingMiddleware` — structured error responses, error stats for `/metrics`
- `ResponseLimitingMiddleware` — caps response size to protect slow clients
- Registration wiring in `configure_middleware(mcp, config)`
- `tests/unit/test_middleware.py` slices covering each middleware

## Configuration surface

| Env var | Default | Purpose |
|---|---|---|
| `INFRAHUB_MCP_RATE_LIMIT_RPS` | `0` | Sustained requests per second; `0` = disabled |
| `INFRAHUB_MCP_RATE_LIMIT_BURST` | `0` | Token-bucket burst capacity; `0` = auto (2× RPS) |
| `INFRAHUB_MCP_RETRY_MAX_ATTEMPTS` | `0` | Max retry attempts; `0` = disabled |
| `INFRAHUB_MCP_RETRY_BASE_DELAY` | `1.0` | Initial retry delay in seconds |
| `INFRAHUB_MCP_CACHE_ENABLED` | `false` | Enable response caching |
| `INFRAHUB_MCP_CACHE_LIST_TTL` | `300` | TTL for list operations (tools, resources, prompts) in seconds |
| `INFRAHUB_MCP_CACHE_READ_TTL` | `3600` | TTL for read operations in seconds |

All env vars above are already parsed into `ServerConfig` in PR 1; this slice lights up the behavior.

## Validation

- Unit tests: `tests/unit/test_middleware.py`
- Manual: set `INFRAHUB_MCP_RATE_LIMIT_RPS=2`; hammer with 10 requests, verify throttling. Set `INFRAHUB_MCP_CACHE_ENABLED=true`; call `list_tools` twice, verify only one downstream call on the second.

## Open questions / follow-ups

*TBD at PR open.*

## Links

- PR: *(fill in when opened)*
- Jira: [INFP-411](https://opsmill.atlassian.net/browse/INFP-411)
