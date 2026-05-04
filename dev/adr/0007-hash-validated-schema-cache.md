# 7. Hash-validated schema cache for passthrough auth modes

**Status:** Accepted
**Date:** 2026-05-04
**Author:** @bkohler

## Context

In the `token-passthrough` and `basic-passthrough` authentication modes, `get_client(ctx)` constructs a fresh `InfrahubClient` per request from the caller's credentials. Each fresh client has an empty per-client SDK schema cache (`client.schema.cache`), so every schema-touching tool — `get_schema`, `get_nodes`, `node_upsert`, the `infrahub://schema*` resources — paid a full `/api/schema` round-trip per request. In bursty agent workloads this dominates request latency and load on Infrahub.

The Infrahub server exposes a cheap `GET /api/schema/summary` endpoint that returns a small `SchemaBranchHash` payload (`{main, nodes, generics}` of hash strings) — no schema body. The SDK already supports `client.schema.set_cache(branch_schema, branch)` to pre-populate a fresh client's cache, and `BranchSchema.hash` mirrors the `/summary.main` field. The `/summary` endpoint is not yet exposed as a public SDK method.

`ResponseCachingMiddleware` already TTL-caches resource reads and the `get_schema` tool when `INFRAHUB_MCP_CACHE_ENABLED=true`. That cache is purely time-based; it cannot detect schema changes within its TTL window, so it short-circuits any deeper correctness layer.

## Decision

Introduce a process-wide, hash-validated schema cache anchored on `AppContext`, with explicit helper functions in `src/infrahub_mcp/schema_cache.py` consumed by every code path that needs schema data.

- Cache scope: passthrough modes only (`schema_cache_enabled` defaults to `True`). Other auth modes already benefit from the SDK's per-client cache via the shared lifespan client.
- Cache key: branch name only. Schema content is global per branch in Infrahub — per-user filtering applies to node data, not to schema definitions.
- Cache value: an immutable `CachedSchemaEntry` carrying the `BranchSchema`, the schema hash, the cached GraphQL SDL string, the monotonic timestamp of the last successful fetch, and a consecutive-revalidation-failure counter.
- Cache currency: a configurable skip-window (`schema_cache_ttl`, default 30 s) lets bursts serve from cache without any upstream call. Past the skip-window the helper calls `/api/schema/summary` and compares `main` against the cached `BranchSchema.hash`. Match extends the entry; differ triggers a full refetch under the cache lock.
- Single-flight: a single `asyncio.Lock` per `AppContext` with double-checked locking guarantees exactly one upstream fetch per cache-miss event under bursts.
- Resilience: 4xx, 5xx, and network failures during revalidation/refetch are treated uniformly — preserve the existing entry, increment its `consecutive_failures`, emit a WARN log. Sustained failures are bounded by two configurable circuit-break thresholds (`schema_cache_max_consecutive_failures` default 10, `schema_cache_max_staleness_seconds` default 900). When either threshold is crossed the entry is marked unsafe and reads return a `ToolError` until a successful revalidation resets both counters. Setting either threshold to 0 disables it.
- 404 from `/summary` evicts the cache entry for that branch.
- The `/api/schema/summary` call uses `client._get(...)` because the SDK does not yet expose a public wrapper. This mirrors the precedent set by the GraphQL SDL fetch in `resources/schema.py`. An upstream SDK PR adding `client.schema.summary()` is a planned follow-up.
- Successful fetches call `client.schema.set_cache(branch_schema, branch)` so subsequent `client.schema.*` calls within the same request hit the SDK cache transparently — the helper is the only place that knows about the cache, but every existing code path benefits.
- A thin `_SchemaAwareResponseCachingMiddleware` subclass of `ResponseCachingMiddleware` bypasses caching for `infrahub://schema*` and `infrahub://graphql-schema` URIs, and `get_schema` is moved to `excluded_tools`. The new schema cache is the single layer that owns correctness for those endpoints.

## Consequences

### Positive

- Repeat schema reads in passthrough modes incur zero upstream calls within the skip-window.
- Schema changes propagate within `schema_cache_ttl + one /summary round-trip` bound — no manual cache flush required after upstream schema edits.
- A 10-coroutine burst against a cold cache results in exactly one upstream full fetch (verified by single-flight test).
- Internal call paths that consume the SDK's `client.schema.*` API (write tools, node tools) benefit transparently because `set_cache(...)` primes the fresh client.
- Sustained Infrahub outages eventually fail closed instead of indefinitely serving silently-stale schema; routine restarts ride through.
- Six new aggregate metrics counters give operators direct visibility into hit ratio, hash-flip rate, revalidation failures, and circuit-break activations.

### Negative

- Direct use of `client._get(/api/schema/summary)` bypasses the SDK's public surface. Mitigated by an upstream SDK PR adding `client.schema.summary()`; the call is co-located in one helper and trivially swappable.
- Configuration changes to `INFRAHUB_MCP_SCHEMA_CACHE_*` require server restart (consistent with all other `ServerConfig` fields).
- Per-branch detail is intentionally absent from Prometheus counters to avoid cardinality blow-up from session-branch auto-creation; per-branch detail goes to WARN/ERROR logs only.

### Neutral

- The cache is process-local. Multi-replica deployments will each maintain an independent cache; cross-process coherence is out of scope and is addressed (if needed) by Redis-backed caching in a follow-up.
- No bounded LRU eviction. Branches in active use are bounded enough in realistic deployments that an in-memory dict is acceptable. A dedicated branch-explosion incident would prompt revisiting.

## Alternatives Considered

### Pre-populate the SDK cache inside `get_client()` itself

Make `get_client(ctx)` async and call `set_cache(...)` before returning the client. Rejected because it (a) makes every code path implicitly pay the schema-revalidation cost, including paths that never touch the schema (e.g. `tools/gql.py`); (b) widens `get_client`'s responsibility from credential plumbing to schema management; (c) hurts testability — every consumer of `get_client` would need a schema-cache fixture. The explicit helper variant keeps the data flow visible at call sites.

### Cache only the post-processed payloads (catalog dict, kind detail dict, SDL string)

Cache the resource outputs rather than the raw `BranchSchema`. Rejected because internal `client.schema.get(kind=...)` calls inside write/node tools would still go to Infrahub. Caching at the `BranchSchema` level lets every consumer benefit via `set_cache(...)` for free; CPU cost of re-deriving the catalog/detail dicts on every read is negligible.

### TTL-only invalidation (no hash check)

Refresh after N seconds, accept staleness within the window. Rejected because it fails the bounded-staleness guarantee — a 5-minute TTL means schema renames take up to 5 minutes to propagate, which breaks tools that validate user input against a now-renamed attribute. Hash check via `/summary` adds one cheap round-trip past the skip-window for tight correctness without a full schema fetch.

### Differentiate auth errors from transient errors during revalidation

Bubble 4xx errors from `/summary` instead of serving stale. Rejected because schema content is global per branch — serving cached schema after an auth blip does not leak per-token-protected data, and bubbling auth errors would block legitimate cached reads during transient auth issues for marginal benefit.

### Indefinite stale-serving on sustained failure

Trust cached data forever during an outage. Rejected because operators need a clear failure mode when the upstream truly diverges from cached state. The two-threshold circuit-break (consecutive failures or absolute staleness) gives bounded staleness with a fail-closed exit, while letting routine restarts ride through.

## References

- Spec: `specs/archive/20260504-203256-schema-cache/spec.md`
- Plan: `specs/archive/20260504-203256-schema-cache/plan.md`
- Research: `specs/archive/20260504-203256-schema-cache/research.md`
- Quickstart: `specs/archive/20260504-203256-schema-cache/quickstart.md`
- Implementation: `src/infrahub_mcp/schema_cache.py`, `src/infrahub_mcp/middleware.py:_SchemaAwareResponseCachingMiddleware`
