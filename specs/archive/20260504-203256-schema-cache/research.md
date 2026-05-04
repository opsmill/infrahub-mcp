# Phase 0 — Research

**Feature**: Hash-Validated Schema Cache
**Date**: 2026-05-04

This document records the design-research questions resolved before implementation. Most decisions were captured during the brainstorm and `/speckit-clarify` session; this file consolidates them in the standard `Decision / Rationale / Alternatives Considered` form.

---

## R1 — Where to anchor the cache lifetime

**Decision**: `AppContext` (process-wide for the server lifetime; one `AppContext` instance is yielded by `app_lifespan` for the entire server process).

**Rationale**:
- `app_lifespan` in `server.py:73` is an `@asynccontextmanager` that yields a single `AppContext` for the server's lifetime — not per-connection or per-request. Verified by reading the lifespan implementation.
- Existing precedent: `default_branch` and `session_branch` are already cached on `AppContext` via the same `asyncio.Lock` + double-checked locking pattern (`utils.py:170–213`).
- An external store (Redis) is overkill for a single-process server (FR-016) and adds operational complexity.

**Alternatives considered**:
- Module-level singleton — same lifetime in practice but weaker isolation in tests.
- External cache (Redis) — adds infra not needed for the in-scope deployment topology.
- Per-connection cache — would not survive across MCP requests in stateless HTTP transports; AppContext already lives at the right scope.

---

## R2 — How to detect schema currency without fetching the full schema

**Decision**: `GET /api/schema/summary?branch=<branch>` on the Infrahub server, returning a `SchemaBranchHash` payload with `main`, `nodes`, and `generics` hash fields. Compare the cached `BranchSchema.hash` against the response's `main` field.

**Rationale**:
- Endpoint exists in `infrahub/backend/infrahub/api/schema.py:224` and is cheap (small JSON response with hashes only, no schema body).
- `BranchSchema.hash` returned from `_fetch()` (`infrahub_sdk/schema/main.py:393`) is set from `data.main`, the same field returned by `/summary` — so equality comparison is well-defined.
- The SDK does **not** currently expose a public wrapper for `/summary`; only `in_sync()` (returns a boolean about worker consistency, not the hash). Direct call via `client._get()` follows the precedent already set by the GraphQL SDL fetch in `resources/schema.py:79`.

**Alternatives considered**:
- `client.schema.in_sync()` — returns boolean about Infrahub worker convergence, not currency relative to our cache. Wrong semantics.
- `BranchData.has_schema_changes` (from the GraphQL Branch query) — boolean about pending proposed changes, not committed-state hash. Wrong semantics.
- Fetch the full schema every revalidation — defeats the purpose of caching.

**Follow-up**: Open an upstream PR adding `async def summary(branch=None) -> SchemaBranchHash` to `infrahub_sdk/schema/__init__.py`. Once released, swap the direct `_get()` call for the public method.

---

## R3 — How to make existing call sites benefit from the cache

**Decision**: Introduce explicit cache helpers in `schema_cache.py`:

```python
async def get_cached_branch_schema(ctx: Context, branch: str | None = None) -> BranchSchema: ...
async def get_cached_graphql_sdl(ctx: Context, branch: str | None = None) -> str: ...
```

Refactor the 12 `client.schema.*` call sites to obtain a `BranchSchema` (or look up a kind from one) via these helpers instead of calling the SDK directly per-request.

**Rationale**:
- Explicit helpers are visible in code review and stack traces.
- `get_client()` stays sync and side-effect-free — no implicit network I/O on every call.
- `tools/gql.py` and similar paths that don't touch schema continue to skip the cache entirely.

**Alternatives considered**:
- Pre-populate the SDK's per-client cache via `client.schema.set_cache(...)` inside `get_client()` itself. Pro: zero call-site changes. Con: makes `get_client()` async + network-bound; couples client construction to schema concerns; surprises in tests; can't easily distinguish branches at construction time.
- Hybrid (set_cache for the default branch, helpers for others). Two patterns to maintain — rejected for added complexity.

---

## R4 — What to cache: structured schema vs post-processed payloads

**Decision**: Cache the raw `BranchSchema` object plus the GraphQL SDL string. Both gated by the same hash.

**Rationale**:
- The SDK's `set_cache()` method accepts a `BranchSchema` and feeds it back into a fresh client's `client.schema.cache` dict. This means a fresh `InfrahubClient` per request, after `set_cache()`, responds to `client.schema.all()` and `client.schema.get(kind=...)` from cache for free — no further changes needed at the SDK layer.
- Post-processed payloads (catalog dict, detail dict) are cheap CPU operations on a loaded `BranchSchema`. Caching them is a redundant layer.
- The GraphQL SDL is not part of `BranchSchema` (fetched separately via `/schema.graphql`); cache it as an independent string keyed by branch but invalidated together with the structured schema using the same hash equality.

**Alternatives considered**:
- Cache only post-processed payloads (catalog/detail/SDL). Bypasses SDK entirely but doesn't help internal `client.schema.get(kind=...)` calls in `tools/write.py`, `tools/nodes.py`. Rejected as incomplete coverage.
- Cache both layers. Complicates invalidation; rejected per Principle VII (simplicity).

---

## R5 — Concurrency model

**Decision**: Single `_schema_cache_lock: asyncio.Lock` per cache type on `AppContext`. Double-checked locking (re-read cache after acquiring lock). Lock-free reads via storage of an immutable `(BranchSchema, hash, fetched_at, consecutive_failures)` tuple — atomic dict assignment in CPython under the GIL ensures readers never see a torn intermediate.

**Rationale**:
- Mirrors the `_default_branch_lock` pattern already in `AppContext`.
- Branch-level contention is low in realistic workloads; per-branch lock map adds state without observable benefit.
- Single-flight guarantees on cold-fetch and stale-hash refetch (FR-007, SC-003) — exactly one upstream full-fetch per cache-miss event.

**Alternatives considered**:
- Per-branch lock map. Lower theoretical contention but unnecessary in practice (branches are tens, not thousands; refetches are minutes-rare events).
- No lock (accept duplicate fetches). Wastes upstream bandwidth on bursts; violates SC-003.

---

## R6 — Interaction with `ResponseCachingMiddleware`

**Decision**: Strip the schema URIs (`infrahub://schema`, `infrahub://schema/{kind}`, `infrahub://graphql-schema`) and the `get_schema` tool from `ResponseCachingMiddleware`. The new hash-validated cache becomes the single owner of correctness for these endpoints. Other resources/tools keep their existing middleware caching.

**Rationale**:
- FR-011 mandates a single layer owns correctness; otherwise the middleware's TTL would short-circuit resource reads with a 5-minute stale window regardless of our 30-second hash check.
- The existing `cache_read_ttl` keeps governing non-schema resources (which the new cache does not touch).

**Implementation note**: `middleware.py:756–767` constructs `ResponseCachingMiddleware`. FastMCP's `ReadResourceSettings` and `CallToolSettings` accept `excluded_resources` / `excluded_tools` (verify exact API name during implementation; if unavailable, narrow `included_tools` to omit `get_schema` and pass an explicit `excluded_resources` set or a custom `should_cache` predicate).

**Alternatives considered**:
- Keep middleware caching as-is. Defeats the new cache's correctness guarantee for resource reads.
- Align TTLs (`cache_read_ttl == schema_cache_ttl`). Forces other non-schema resources into a tighter TTL than they need.

---

## R7 — Error policy on revalidation/refetch failures

**Decision**: All upstream failures during revalidation or refetch (4xx authentication errors, 5xx server errors, network errors) are treated uniformly as transient: serve stale cache + emit WARN log. Cold-cache fetch failure bubbles to the agent (FR-009). Sustained failures are bounded by two configurable circuit-break thresholds (FR-009a): consecutive-failure ceiling (default 10) and absolute-staleness ceiling (default 900 seconds).

**Rationale**:
- Schema content is global per branch (FR-017) — serving cached schema after an auth blip does not leak per-token-protected data.
- Differentiating 4xx from 5xx adds error-classification complexity without security benefit.
- Circuit-break thresholds prevent unbounded stale-serving in genuine sustained outages while allowing routine restarts to ride through.

**Alternatives considered**:
- Bubble all errors strictly. Hard-fails legitimate cached reads on transient blips.
- Differentiate 4xx (bubble) from 5xx (serve stale). Adds branching for marginal benefit.
- Indefinite stale-serving. User explicitly rejected during clarify session (Q3 → B+C).

---

## R8 — Branch eviction on upstream deletion

**Decision**: No eager eviction. Rely on the next `/api/schema/summary` call returning 404 for a deleted branch — when this happens, evict the cache entry for that branch.

**Rationale**:
- The MCP server does not expose `branch.delete` or `branch.merge` as tools (verified via grep). No in-server signal drives eager eviction.
- 404-on-summary is a clear deterministic signal; the eviction logic is naturally co-located with the revalidation path.

**Alternatives considered**:
- Periodic GC sweep. Adds a background task for an event that is naturally driven by access patterns.
- Branch-list polling. Adds upstream load for no observable benefit.

---

## R9 — Configuration shape

**Decision**: Four new `ServerConfig` fields:

| Field | Type | Default | Purpose |
|---|---|---|---|
| `schema_cache_enabled` | `bool` | `True` | Master switch (FR-013). |
| `schema_cache_ttl` | `int` (seconds) | `30` | Skip-window — how often to revalidate via summary (FR-014). |
| `schema_cache_max_consecutive_failures` | `int` | `10` | Circuit-break: N consecutive revalidation failures (FR-014a). 0 disables. |
| `schema_cache_max_staleness_seconds` | `int` | `900` | Circuit-break: T seconds since last successful revalidation (FR-014a). 0 disables. |

All settings load from environment variables prefixed with `INFRAHUB_MCP_` per existing `pydantic-settings` convention. Configuration changes require server restart (clarified Q1).

**Rationale**: Matches the spec's clarified knobs exactly. No LRU cap (per brainstorm Q11; spec assumption). Restart-required keeps consistent with all other `ServerConfig` fields.

---

## R10 — Metrics

**Decision**: Six new aggregate counters (no per-branch labels) registered with the existing `metrics` module:

- `schema_cache_hits` — request served from cache without revalidation (skip-window active).
- `schema_cache_misses` — cold fetch.
- `schema_cache_hash_matches` — `/summary` returned same hash; cache extended.
- `schema_cache_hash_diffs` — `/summary` returned different hash; full refetch performed.
- `schema_cache_revalidate_failures` — F1/F2 transient failures (cache served stale).
- `schema_cache_circuit_breaks` — entry marked unsafe by either threshold.

Per-branch detail appears in WARN log lines for revalidate-failures and circuit-breaks (clarified Q5).

**Rationale**: Matches spec FR-012. Aggregate-only avoids Prometheus cardinality blow-up from short-lived session branches with `{hex}` placeholders.

---

## R11 — Test strategy

**Decision**: Unit tests with mocked `InfrahubClient` covering all paths plus a single-flight concurrency test using `asyncio.gather`.

Test surface:
1. Cold cache → first request fetches.
2. Warm cache within skip-window → no upstream call.
3. Past skip-window, hash matches → `/summary` called once, no full refetch.
4. Past skip-window, hash differs → `/summary` called, then full refetch, cache replaced.
5. `SchemaNotFoundError` on cached kind, hash matches → propagate error.
6. `SchemaNotFoundError` on cached kind, hash differs → refetch + retry.
7. Concurrent cold-fetch (10 coroutines) → exactly one `_fetch()` call.
8. F1: `/summary` fails with cache present → serve stale + warn.
9. F2: refetch fails with cache present → serve stale + warn.
10. F3: cold fetch fails → bubble.
11. Disabled flag → no caching, behaviour identical to today.
12. Consecutive-failure threshold reached → circuit-break, reads fail-closed.
13. Absolute-staleness threshold reached → circuit-break, reads fail-closed.
14. Successful revalidation after circuit-break → counter reset, reads serve again.
15. 404 from `/summary` → entry evicted.

**Test file**: `tests/unit/test_schema_cache.py`. Mirrors source layout per Constitution Principle V.

**Rationale**: TDD per Constitution Principle V and `superpowers:test-driven-development` skill. Mocked client keeps tests fast and deterministic. Single end-to-end test of the middleware-exclusion change verifies the wiring (rather than unit-testing FastMCP internals).

---

## R12 — Out of scope (deferred)

- Multi-replica / shared cache (Redis). Single-process scope (FR-016).
- Bounded LRU eviction. Branch counts in realistic deployments are small.
- Cache for non-schema resources. Existing `ResponseCachingMiddleware` already covers them.
- Schema-mutation invalidation hooks. The MCP server does not expose schema-write tools.
- Live config reload. All `ServerConfig` fields require restart.
