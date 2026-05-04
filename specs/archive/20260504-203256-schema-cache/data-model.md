# Phase 1 — Data Model

**Feature**: Hash-Validated Schema Cache
**Date**: 2026-05-04

This document captures the in-memory entities introduced by `schema_cache.py` and the new fields added to existing types. All entities are process-local; no persistence.

---

## Entity: `CachedSchemaEntry`

Immutable snapshot of a single branch's cached schema state. Stored as the value in the schema-cache dict on `AppContext`. Storing it as a single immutable object enables lock-free atomic reads — the dict assignment is atomic under the GIL, and the consumer sees a self-consistent snapshot without holding a lock.

```python
from dataclasses import dataclass, field
from typing import Any  # placeholder; real type is infrahub_sdk.schema.BranchSchema

@dataclass(frozen=True, slots=True)
class CachedSchemaEntry:
    branch: str                  # Resolved canonical branch name (None already mapped to default)
    schema: BranchSchema          # SDK's BranchSchema; loaded into fresh clients via set_cache()
    schema_hash: str              # BranchSchema.hash at fetch time; equality test against /summary.main
    graphql_sdl: str              # Cached GraphQL SDL string; invalidated together with schema
    fetched_at_monotonic: float   # asyncio.get_event_loop().time() at last successful fetch/revalidation
    consecutive_failures: int     # Count of revalidation failures since last success; 0 when fresh
```

**Invariants**:
- `branch` is non-empty and is the canonical resolved name (FR-015).
- `schema_hash` is non-empty (set from `BranchSchema.hash` after a successful fetch).
- `consecutive_failures >= 0`.
- `fetched_at_monotonic` is monotonic-clock time; do not compare against wall-clock or persist.

**State transitions**:

| Trigger | New entry produced |
|---|---|
| Cold fetch succeeds | `consecutive_failures = 0`, `fetched_at_monotonic = now`, hash + schema + SDL populated |
| Hash matches at revalidation | Same `schema` and `schema_hash`; `fetched_at_monotonic = now`, `consecutive_failures = 0` |
| Hash differs at revalidation | New `schema`, `schema_hash`, `graphql_sdl`; `fetched_at_monotonic = now`, `consecutive_failures = 0` |
| Revalidation fails (F1) | `schema/schema_hash/graphql_sdl` unchanged; `fetched_at_monotonic` unchanged; `consecutive_failures += 1` |
| Refetch fails (F2) after hash diff | Same as F1: previous entry is preserved |
| `/summary` returns 404 | Entry removed from dict (no replacement entry produced) |
| Consecutive-failure threshold reached | Entry remains in dict but `is_circuit_broken()` returns True; reads fail-closed |
| Absolute-staleness threshold reached | Entry remains in dict but `is_circuit_broken()` returns True; reads fail-closed |

**Methods (computed properties on the dataclass)**:

```python
def is_circuit_broken(self, *, max_consecutive_failures: int, max_staleness_seconds: int, now: float) -> bool:
    """Return True iff either configured threshold has been crossed.

    A threshold value of 0 disables that threshold entirely.
    """
    if max_consecutive_failures and self.consecutive_failures >= max_consecutive_failures:
        return True
    if max_staleness_seconds and (now - self.fetched_at_monotonic) >= max_staleness_seconds:
        return True
    return False

def is_within_skip_window(self, *, skip_window_seconds: int, now: float) -> bool:
    """Return True iff the cache may be served without revalidation."""
    return (now - self.fetched_at_monotonic) < skip_window_seconds
```

---

## Entity changes: `AppContext` (in `utils.py`)

Three new fields, mirroring the existing `default_branch` + `_default_branch_lock` pattern:

```python
@dataclass
class AppContext:
    # ...existing fields...
    schema_cache: dict[str, CachedSchemaEntry] = field(default_factory=dict)
    _schema_cache_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
```

Note: `graphql_sdl` lives on the `CachedSchemaEntry` itself (not a separate dict) so the SDL stays in lockstep with the structured schema and shares the same hash gate.

---

## Configuration: `ServerConfig` (in `config.py`)

Four new pydantic-settings fields:

```python
schema_cache_enabled: bool = True
schema_cache_ttl: int = 30
schema_cache_max_consecutive_failures: int = 10
schema_cache_max_staleness_seconds: int = 900
```

All four read from `INFRAHUB_MCP_*` environment variables per existing convention. `schema_cache_max_consecutive_failures = 0` and `schema_cache_max_staleness_seconds = 0` each disable that respective circuit-break threshold; setting both to 0 yields unbounded stale-serving (Option A from clarify session).

---

## Public API: `schema_cache.py`

```python
async def get_cached_branch_schema(ctx: Context, branch: str | None = None) -> BranchSchema:
    """Return the cached BranchSchema for *branch*, fetching/revalidating as needed.

    Resolves None → default branch via existing get_default_branch(ctx) (FR-015).
    Honors skip-window TTL, hash-validated revalidation, lazy refetch on missing kinds,
    serve-stale on transient failures, and circuit-break thresholds.
    """

async def get_cached_graphql_sdl(ctx: Context, branch: str | None = None) -> str:
    """Return the cached GraphQL SDL for *branch*, sharing hash gating with get_cached_branch_schema."""
```

Both are async. Both raise `ToolError` (or `ResourceError` from the calling resource) when:
- The cache is empty AND a cold fetch fails (F3).
- A circuit-break threshold has been crossed for the requested branch.

Both never raise on transient revalidation failures when a cached entry exists; instead they emit a WARN log line and serve stale.

**Internal helpers** (private to the module):
- `_fetch_summary_hash(client, branch)` — calls `client._get(/api/schema/summary?branch=...)`, returns the `main` field. Raises if 404 (caller evicts).
- `_full_fetch(client, branch)` — calls `client.schema._fetch(branch)` and `client._get(/schema.graphql)`, returns the new `CachedSchemaEntry`.
- `_install_cache_into_client(client, entry)` — calls `client.schema.set_cache(entry.schema, entry.branch)` so subsequent `client.schema.*` calls within this request hit the SDK cache.

---

## Metrics counters (registered with the existing metrics module)

Aggregate `Counter` types — no labels:

| Name | Increment when |
|---|---|
| `schema_cache_hits` | Cache served without revalidation (skip-window active). |
| `schema_cache_misses` | Cold fetch performed (no entry existed). |
| `schema_cache_hash_matches` | `/summary` confirmed unchanged hash; cache extended. |
| `schema_cache_hash_diffs` | `/summary` returned a different hash; full refetch performed. |
| `schema_cache_revalidate_failures` | Either `/summary` or full refetch failed transiently (F1/F2). |
| `schema_cache_circuit_breaks` | An entry was first observed as circuit-broken in this request (idempotent — fires once per state transition, not per request thereafter). |

---

## Failure semantics summary

| Condition | Outcome | Counter | Log |
|---|---|---|---|
| Cache hit within skip-window | Serve cached | `schema_cache_hits++` | (none) |
| Cache hit past skip-window, hash match | Serve cached, extend timestamp | `schema_cache_hash_matches++` | (none) |
| Cache hit past skip-window, hash diff | Refetch, replace, serve fresh | `schema_cache_hash_diffs++` | (none) |
| Cache miss | Cold fetch, populate, serve fresh | `schema_cache_misses++` | (none) |
| `/summary` failure (any error) | Serve stale, increment failure counter on entry | `schema_cache_revalidate_failures++` | WARN with branch name + exception |
| Refetch failure after detected hash diff | Serve stale, increment failure counter on entry | `schema_cache_revalidate_failures++` | WARN with branch name + exception |
| `/summary` 404 | Evict entry; subsequent reads are cache misses | (none specific) | WARN: branch removed |
| Circuit-break threshold crossed | Fail closed; raise ToolError to agent | `schema_cache_circuit_breaks++` (once per state transition) | ERROR with branch name + which threshold + last-success time |
| Successful revalidation/refetch | Reset `consecutive_failures` to 0; circuit-break clears | (existing hit/diff counter applies) | (none) |
| Cold fetch failure (no cache) | Bubble error to agent | (none specific) | ERROR with branch name + exception |
| `SchemaNotFoundError` on cached kind, hash matches | Propagate the not-found error | `schema_cache_hash_matches++` | (none) |
| `SchemaNotFoundError` on cached kind, hash differs | Refetch, retry, return result | `schema_cache_hash_diffs++` | (none) |
