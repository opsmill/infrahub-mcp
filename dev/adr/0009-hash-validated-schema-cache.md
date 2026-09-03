# 9. Hash-validated schema cache for passthrough auth modes

**Status:** Accepted
**Date:** 2026-05-04
**Author:** @bkohler

## Context

In the `token-passthrough` and `basic-passthrough` authentication modes, `get_client(ctx)` constructs a fresh `InfrahubClient` per request from the caller's credentials. Each fresh client has an empty per-client SDK schema cache (`client.schema.cache`), so every schema-touching tool — `get_schema`, `get_nodes`, `node_upsert`, the `infrahub://schema*` resources — paid a full `/api/schema` round-trip per request. In bursty agent workloads this dominates request latency and load on Infrahub.

The Infrahub server exposes a cheap `GET /api/schema/summary` endpoint that returns a small `SchemaBranchHash` payload (`{main, nodes, generics}` of hash strings) — no schema body. The SDK already supports `client.schema.set_cache(branch_schema, branch)` to pre-populate a fresh client's cache, and `BranchSchema.hash` mirrors the `/summary.main` field. The `/summary` endpoint is not yet exposed as a public SDK method.

`ResponseCachingMiddleware` already TTL-caches resource reads and the `get_schema` tool when `INFRAHUB_MCP_CACHE_ENABLED=true`. That cache is purely time-based; it cannot detect schema changes within its TTL window, so it short-circuits any deeper correctness layer.

## Decision

Introduce a process-wide, hash-validated schema cache anchored on `AppContext`, with explicit helper functions in `src/infrahub_mcp/schema_cache.py` consumed by every code path that needs schema data.

- Cache scope: every auth mode (`schema_cache_enabled` defaults to `True`). Passthrough is the motivating case, but the helpers are the single schema entry point for all modes rather than a second code path guarded by `auth_mode`. In `none`/`oidc` the shared lifespan client made this look unnecessary — and it is not: `client.schema.all()` populates its per-client cache once and never revalidates it, so those modes previously served schema of *unbounded* age until restart. Routing them through the same hash-validated helpers bounds that staleness. The cost is that the circuit breaker now applies there too, which is the intended failure mode.
- Cache key: branch name only. Schema content is global per branch in Infrahub — per-user filtering applies to node data, not to schema definitions (spec FR-017). Passthrough callers therefore share entries safely. This is the one assumption the shared key rests on: if Infrahub ever filters schema visibility per credential, the key must gain the caller's authorization identity.
- Cache value: an immutable `CachedSchemaEntry` carrying the `BranchSchema`, the schema hash, the cached GraphQL SDL string (`None` when only that fetch failed — see below), the monotonic timestamp of the last successful fetch, and a consecutive-revalidation-failure counter.
- Cache currency: a configurable skip-window (`schema_cache_ttl`, default 30 s) lets bursts serve from cache without any upstream call. Past the skip-window the helper calls `/api/schema/summary` and compares `main` against the cached `BranchSchema.hash`. Match extends the entry; differ triggers a full refetch under the cache lock.
- Single-flight: a single `asyncio.Lock` per `AppContext` with double-checked locking guarantees exactly one upstream fetch per cache-miss event under bursts.
- Resilience: 4xx, 5xx, and network failures during revalidation/refetch are treated uniformly — preserve the existing entry, increment its `consecutive_failures`, emit a WARN log. Sustained failures are bounded by two configurable circuit-break thresholds (`schema_cache_max_consecutive_failures` default 10, `schema_cache_max_staleness_seconds` default 900). When either threshold is crossed the entry is marked unsafe and reads return a `ToolError`. The breaker is not a latch: a read against a broken entry still attempts revalidation and fails closed only if that attempt also fails, so the cache heals itself once Infrahub recovers. Upstream probes are throttled to one per `min(schema_cache_ttl, 30 s)` per branch (tracked by `last_attempt_monotonic`, distinct from the last-success timestamp) from the first failure onward, not only once the breaker has tripped: a read that lands inside the window after a failed probe serves the stale entry while the entry is under both thresholds and fails fast once it has tripped, so a failing branch costs one upstream timeout per window rather than one per request. Without the pre-trip throttle, concurrent reads during an outage serialized on the cache lock — each paying its own upstream timeout — until the failure count reached the threshold. The 30-second ceiling keeps recovery latency independent of the skip-window, which an operator may widen to hours purely to cut steady-state load. Setting either threshold to 0 disables the breaker; setting `schema_cache_ttl` to 0 disables the throttle.
- A kind absent from the cached `BranchSchema` (`get_cached_kind`) forces one revalidation past the skip-window, so a kind added upstream is found before the window elapses. Forced probes are debounced to one per 2 s per branch on `last_attempt_monotonic` — any attempt counts, successful or failed — and honour the failure throttle and the breaker like any other read, since a missing kind says nothing about upstream health. Misses are rare (`BranchSchema.nodes` already folds nodes, generics, profiles and templates together, so a cached kind's relationship peers are present) but they cluster — a retried mistyped kind, `schema.py` gathering peers and `tools/nodes.py` looping over them when a peer really is unknown, concurrent misses queued behind one probe — and each one used to pay its own `/summary` round-trip under the cache lock. The debounce is deliberately short and independent of `schema_cache_ttl`: long enough to coalesce one call's fan-out and a short retry burst, short enough that the next miss still finds a kind added upstream.
- A failed *cold* fetch (no entry to serve stale from) is remembered per branch in `AppContext.schema_cache_cold_failures` for the same window; reads inside it fail fast with a `ToolError` instead of taking the lock and probing again, and the next successful cold fetch clears the marker. Without it an empty cache during an outage never self-limited, because no entry — and so no failure counter — existed for the breaker to act on. `BranchNotFoundError` from an unknown branch is not remembered and keeps surfacing unchanged; every other failure is treated uniformly, as on the revalidation path.
- A branch-gone response from `/summary` evicts the cache entry for that branch and raises the SDK's public `BranchNotFoundError`, matching what a cold cache miss raises from `/api/schema`. Branch-gone means HTTP 400 or 404: Infrahub's `BranchNotFoundError` carries `HTTP_CODE = 400` and is raised by the endpoint's branch dependency, so 400 is what a deleted branch actually returns (the SDK maps 400 from `/api/schema` the same way); 404 is accepted as the generic not-found signal. The private sentinel used internally never escapes the module.
- The `/api/schema/summary` call uses `client._get(...)` because the SDK does not yet expose a public wrapper. An upstream SDK PR adding `client.schema.summary()` is a planned follow-up. The GraphQL SDL, by contrast, goes through the SDK's public `client.schema.get_graphql_schema(branch=...)`; it is cached alongside the structured schema for the same branch, so the branch is threaded through rather than defaulted.
- The SDL is fetched together with the structured schema on every cold fetch and hash-diff refetch, so the two describe the same upstream state, but an SDL failure alone is not fatal. `/schema.graphql` is a heavier endpoint with exactly one consumer (`infrahub://graphql-schema`); letting it fail the whole fetch would take down every node and schema tool — and, on a cold cache, arm the cold-failure marker — for an outage those tools never depend on. Instead the entry is stored with `graphql_sdl = None` and a WARN is logged; the next `infrahub://graphql-schema` read fills the SDL lazily under the cache lock, and if that fetch fails too the resource fails on its own without touching the failure counter or the breaker. A fully lazy SDL (fetched only on first read) was rejected: it would let the SDL trail the structured schema by up to a skip-window after a hash flip, which is the structured-vs-SDL drift the spec treats as a correctness defect.
- Successful fetches call `client.schema.set_cache(branch_schema, branch)` so subsequent `client.schema.*` calls within the same request hit the SDK cache transparently — the helper is the only place that knows about the cache, but every existing code path benefits.
- A thin `_SchemaAwareResponseCachingMiddleware` subclass of `ResponseCachingMiddleware` bypasses caching for `infrahub://schema*` and `infrahub://graphql-schema` URIs, and overrides `on_call_tool` to bypass tool caching entirely. `get_schema` was the only tool ever TTL-cached and the schema cache now owns its freshness; no other tool result is safe to replay. The bypass has to live in the override rather than in `CallToolSettings`, because FastMCP's `_matches_tool_cache_settings` reads `included_tools`/`excluded_tools` with a truthiness check — an empty allowlist reads as "no filter", and `excluded_tools=["get_schema"]` would make every *other* tool cacheable, replaying node queries and mutations.

## Consequences

### Positive

- Repeat schema reads in passthrough modes incur zero upstream calls within the skip-window.
- Schema changes are *detected* within a `schema_cache_ttl + one /summary round-trip` bound, and the new schema is served after the full refetch that a hash difference triggers (`/api/schema` + `/schema.graphql`) — no manual cache flush required after upstream schema edits.
- A 10-coroutine burst against a cold cache results in exactly one upstream full fetch (verified by single-flight test).
- Internal call paths that consume the SDK's `client.schema.*` API (write tools, node tools) benefit transparently because `set_cache(...)` primes the fresh client.
- Sustained Infrahub outages eventually fail closed instead of indefinitely serving silently-stale schema; routine restarts ride through.
- Seven new aggregate metrics counters give operators direct visibility into hit ratio, stale serves during an outage, hash-flip rate, revalidation failures, and circuit-break activations. `circuit_break` counts breaker *transitions*, not reads rejected while broken, so the number reads as "how often did this trip".

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
