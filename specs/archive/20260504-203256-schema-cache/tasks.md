---

description: "Task list for hash-validated schema cache feature"
---

# Tasks: Hash-Validated Schema Cache

**Input**: Design documents from `specs/20260504-203256-schema-cache/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, quickstart.md

**Tests**: Required (TDD per Constitution Principle V).

**Organization**: Tasks grouped by user story so each delivers an independently testable increment. P1 stories (US1 + US2) are the MVP — without hash-validated correctness (US2), US1 alone would ship a stale-data hazard, so the MVP bundles both.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Different file, no dependency on incomplete tasks → safe to parallelise.
- **[Story]**: User story label (US1, US2, US3, US4, US5).
- File paths are absolute relative to repo root.

## Path Conventions

Single-project layout: `src/infrahub_mcp/`, `tests/unit/`. Per `plan.md` Project Structure.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Confirm baseline. No new dependencies required.

- [ ] T001 Verify `uv sync` runs clean and `uv run pytest` is green on `feat/schema-cache` before any changes.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Config knobs, cache entry shape, and `AppContext` fields. Every user story depends on these.

**⚠️ CRITICAL**: No user-story work begins until this phase is complete.

- [ ] T002 [P] Add four new fields to `ServerConfig` in `src/infrahub_mcp/config.py`: `schema_cache_enabled: bool = True`, `schema_cache_ttl: int = 30`, `schema_cache_max_consecutive_failures: int = 10`, `schema_cache_max_staleness_seconds: int = 900`. Read from `INFRAHUB_MCP_*` env vars per existing convention.
- [ ] T003 Create `src/infrahub_mcp/schema_cache.py` with `CachedSchemaEntry` frozen `@dataclass(frozen=True, slots=True)` per `data-model.md`, plus the helper-function signatures (bodies stubbed with `raise NotImplementedError`) so other modules can import them.
- [ ] T004 Extend `AppContext` in `src/infrahub_mcp/utils.py` with `schema_cache: dict[str, CachedSchemaEntry] = field(default_factory=dict)` and `_schema_cache_lock: asyncio.Lock = field(default_factory=asyncio.Lock)`. Use `TYPE_CHECKING` import for `CachedSchemaEntry` to avoid the runtime cycle.

**Checkpoint**: Foundational types exist; user stories may now begin in parallel where dependencies allow.

---

## Phase 3: User Story 1 — Fast schema reads in passthrough modes (Priority: P1) 🎯 MVP slice 1

**Goal**: In passthrough auth modes, repeat schema reads within the skip-window are served from cache with no upstream `/api/schema` round-trip.

**Independent Test**: Per quickstart §2 — first read populates cache, second read within 30 s hits cache; metrics show one miss + one hit; second read latency ≪ first.

### Tests for User Story 1 (write FIRST, ensure RED)

- [ ] T005 [P] [US1] Cold-cache test: in `tests/unit/test_schema_cache.py`, assert `get_cached_branch_schema(ctx, branch="main")` triggers exactly one upstream fetch and populates `app_ctx.schema_cache["main"]`.
- [ ] T006 [P] [US1] Warm-cache-within-skip-window test: second call within `schema_cache_ttl` returns the same `BranchSchema` object with no additional upstream call.
- [ ] T007 [P] [US1] Single-flight test: `asyncio.gather(*(get_cached_branch_schema(ctx) for _ in range(10)))` against a cold cache results in exactly one `client.schema._fetch` call.
- [ ] T008 [P] [US1] Cache-disabled bypass: with `schema_cache_enabled=False`, every `get_cached_branch_schema(ctx)` call performs an upstream fetch (no caching).

### Implementation for User Story 1

- [ ] T009 [US1] Implement `get_cached_branch_schema(ctx, branch=None)` in `src/infrahub_mcp/schema_cache.py` covering: branch resolution via `get_default_branch(ctx)`, double-checked locking, cold-fetch path, and skip-window short-circuit. Hash revalidation handled in US2.
- [ ] T010 [US1] Implement `get_cached_graphql_sdl(ctx, branch=None)` mirroring T009; SDL stored on `CachedSchemaEntry` so it shares the same lock and entry.
- [ ] T011 [US1] In the cold-fetch path, call `client.schema.set_cache(entry.schema, entry.branch)` so subsequent SDK schema lookups inside the same request are served from the SDK's per-client cache.
- [ ] T012 [P] [US1] Refactor `src/infrahub_mcp/schema.py` (`get_schema_catalog`, `get_schema_detail`, `get_valid_kinds_summary`) to obtain the `BranchSchema` once via `get_cached_branch_schema(ctx, branch=branch)` and look up kinds in-memory rather than calling `client.schema.all()` / `client.schema.get(kind=…)` directly.
- [ ] T013 [P] [US1] Refactor `src/infrahub_mcp/resources/schema.py` (`graphql_schema` resource) to use `get_cached_graphql_sdl(ctx)`.
- [ ] T014 [P] [US1] Refactor `src/infrahub_mcp/tools/nodes.py` (3 `client.schema.get(kind=…)` sites at lines 120, 236, 348) to consume the cached `BranchSchema`.
- [ ] T015 [P] [US1] Refactor `src/infrahub_mcp/tools/schema.py` to use the cache helper.
- [ ] T016 [P] [US1] Refactor `src/infrahub_mcp/tools/write.py` (sites at lines 91, 201) to consume the cached `BranchSchema`.

**Checkpoint**: US1 is end-to-end working — cache hits for repeat reads, no upstream calls within skip-window. Tests T005–T008 GREEN.

---

## Phase 4: User Story 2 — Bounded staleness when schema changes (Priority: P1) 🎯 MVP slice 2

**Goal**: Past the skip-window, the cache is validated against `/api/schema/summary`. Hash match extends the cache; hash diff triggers full refetch. `SchemaNotFoundError` on a cached kind triggers hash-validated lazy refetch.

**Independent Test**: Per quickstart §3–4 — schema mutated upstream; first read past skip-window detects hash diff and returns fresh schema.

### Tests for User Story 2

- [ ] T017 [P] [US2] Past-skip-window-hash-match test in `tests/unit/test_schema_cache.py`: cache populated, time advanced past TTL, mocked `/summary` returns the same hash → `_fetch` is NOT called; `fetched_at_monotonic` is bumped.
- [ ] T018 [P] [US2] Past-skip-window-hash-diff test: time advanced past TTL, mocked `/summary` returns a different hash → full refetch is called; cache entry replaced with new `BranchSchema`, new hash.
- [ ] T019 [P] [US2] Lazy-on-NotFound test: `get_cached_branch_schema` returns the cached schema; consumer code raises `SchemaNotFoundError` for a kind absent from cache; helper revalidates via `/summary`; if hash unchanged, propagate; if hash changed, refetch + retry returns the kind. (Test the helper used by call sites that need this — likely a `get_cached_kind(ctx, kind, branch)` wrapper added to `schema_cache.py`.)
- [ ] T020 [P] [US2] 404-evicts test: mocked `/summary` returns 404 (branch deleted upstream) → cache entry for that branch is removed; subsequent call performs cold fetch and propagates the upstream error.

### Implementation for User Story 2

- [ ] T021 [US2] Implement `_fetch_summary_hash(client, branch)` private helper in `src/infrahub_mcp/schema_cache.py`: calls `client._get(f"{client.address}/api/schema/summary?branch={branch}")` (with `# noqa: SLF001  # pylint: disable=protected-access` mirroring `resources/schema.py:79`); returns the `main` field; raises a sentinel `_BranchGone` exception on 404 so the caller can evict.
- [ ] T022 [US2] Extend `get_cached_branch_schema()` to call `_fetch_summary_hash()` past the skip-window, compare against `entry.schema_hash`, and on mismatch perform a full refetch + replace; on match, produce a new `CachedSchemaEntry` with the same schema/hash but updated `fetched_at_monotonic` and zeroed `consecutive_failures`.
- [ ] T023 [US2] Add a `get_cached_kind(ctx, kind, branch=None)` helper that consumes the cached `BranchSchema`, catches `KeyError`/`SchemaNotFoundError`, performs one revalidation cycle, and re-attempts before propagating the error. Update the call sites in `tools/nodes.py`, `tools/write.py`, and `tools/schema.py` to use it where they need a single kind (rather than the whole schema).
- [ ] T024 [US2] Implement 404-eviction: when `_fetch_summary_hash()` raises `_BranchGone`, remove the cache entry under the lock and propagate the original error to the caller.

**Checkpoint**: US2 GREEN. MVP (US1 + US2) is complete and shippable; everything from this point forward hardens resilience and observability.

---

## Phase 5: User Story 3 — Resilience to transient flakes (Priority: P2)

**Goal**: F1 (summary fails) and F2 (refetch fails) serve stale + WARN. F3 (cold + fetch fails) bubbles. Sustained failures bound by configurable circuit-break thresholds.

**Independent Test**: Per quickstart §6–7 — block outbound network; reads continue from cache with WARN logs; after N consecutive failures or T seconds since last success, reads start failing closed; on recovery, counters reset and reads resume.

### Tests for User Story 3

- [ ] T025 [P] [US3] F1 test: cache populated; mocked `/summary` raises a network exception; helper returns the cached schema, increments the entry's `consecutive_failures`, and a WARN log line is emitted with the branch name.
- [ ] T026 [P] [US3] F2 test: cache populated; `/summary` returns a different hash; full refetch raises; helper returns the previously cached schema, increments `consecutive_failures`, WARN log emitted.
- [ ] T027 [P] [US3] F3 test: cache empty; cold fetch raises; helper bubbles the exception; no entry is created.
- [ ] T028 [P] [US3] F1 with auth error (401/403): cache populated; mocked `/summary` raises an `AuthenticationError`; helper still returns the cached schema (uniform handling per FR-008).
- [ ] T029 [P] [US3] Consecutive-failure circuit-break test: drive `consecutive_failures` up to `schema_cache_max_consecutive_failures=10`; the next read raises `ToolError` ("schema unavailable") rather than serving stale.
- [ ] T030 [P] [US3] Absolute-staleness circuit-break test: time-advance past `schema_cache_max_staleness_seconds=900` since the last successful fetch; the next read raises `ToolError`.
- [ ] T031 [P] [US3] Threshold-disabled tests: with each threshold set to 0, the corresponding circuit-break never fires regardless of failure count or time elapsed.
- [ ] T032 [P] [US3] Counter-reset test: after a circuit-break, when revalidation succeeds, `consecutive_failures` returns to 0, `fetched_at_monotonic` is bumped, and reads serve again on the next request.

### Implementation for User Story 3

- [ ] T033 [US3] Wrap `_fetch_summary_hash()` and full-refetch calls in `try/except` blocks that, when an entry is present, replace the entry with a copy that has `consecutive_failures += 1` while preserving `schema`, `schema_hash`, `graphql_sdl`, and `fetched_at_monotonic`. Emit `logger.warning("schema_cache_revalidate_failure branch=%s exception=%r", branch, exc)`.
- [ ] T034 [US3] Add `is_circuit_broken()` and `is_within_skip_window()` methods (or module-level helpers operating on the entry) per `data-model.md`. Use `time.monotonic()` rather than wall clock; respect 0-disables-threshold semantics.
- [ ] T035 [US3] At the top of `get_cached_branch_schema()` (after entry retrieval), check `is_circuit_broken()` and raise `ToolError("Schema temporarily unavailable for branch '<name>': ...")` if tripped. Emit ERROR log on first transition (not on every subsequent request).
- [ ] T036 [US3] On any successful revalidation or refetch, produce a fresh entry with `consecutive_failures=0` (already part of T022); ensure no path writes `consecutive_failures` increment without preserving the previous schema.
- [ ] T037 [US3] In the `get_client()` passthrough path, ensure the cold-fetch failure path (F3) bubbles `ServerNotReachableError`/`AuthenticationError` exactly as today (no swallowing).

**Checkpoint**: US3 GREEN. Cache survives transient blips, surfaces sustained outages explicitly via fail-closed.

---

## Phase 6: User Story 4 — Operator visibility (Priority: P2)

**Goal**: Aggregate counters at `/metrics` reveal hits, misses, hash matches/diffs, revalidation failures, and circuit-breaks. Per-branch detail in WARN/ERROR logs.

**Independent Test**: Per quickstart §2, §6–7 — issue known mix of operations; counters at `/metrics` reflect activity; failure scenarios produce WARN logs naming the branch.

### Tests for User Story 4

- [ ] T038 [P] [US4] Metrics-registration test in `tests/unit/test_schema_cache.py`: confirm all six counters are registered with the metrics module and visible in the JSON snapshot.
- [ ] T039 [P] [US4] Counter-increment tests: drive each cache code path (hit, miss, hash match, hash diff, revalidate failure, circuit-break) and assert the corresponding counter increments by exactly 1.

### Implementation for User Story 4

- [ ] T040 [US4] Register six aggregate counters in `src/infrahub_mcp/metrics.py`: `schema_cache_hits`, `schema_cache_misses`, `schema_cache_hash_matches`, `schema_cache_hash_diffs`, `schema_cache_revalidate_failures`, `schema_cache_circuit_breaks`.
- [ ] T041 [US4] Wire counter increments into `schema_cache.py` at the points described in `data-model.md` — Failure semantics summary table.
- [ ] T042 [US4] Confirm the existing `/metrics` endpoint exposes the new counters in both Prometheus and JSON formats without further code (counters auto-register through the same path as existing FastMCP cache stats).

**Checkpoint**: US4 GREEN. Operators can verify cache effectiveness from metrics alone.

---

## Phase 7: User Story 5 — Operator control (Priority: P3)

**Goal**: `schema_cache_enabled=False` reverts to pre-feature behaviour. `schema_cache_ttl` override is respected.

**Independent Test**: Per quickstart §8 — disable, restart, verify upstream-every-time; re-enable with non-default TTL, verify revalidation timing.

### Tests for User Story 5

- [ ] T043 [P] [US5] Disabled-flag end-to-end test: with `schema_cache_enabled=False`, every schema-touching call performs an upstream fetch (no entries appear in `app_ctx.schema_cache`).
- [ ] T044 [P] [US5] TTL-override test: with `schema_cache_ttl=5`, a second call 6 seconds after the first triggers `/summary` revalidation; with `schema_cache_ttl=300`, a second call 6 seconds later does not.

### Implementation for User Story 5

- [ ] T045 [US5] Add the disabled-flag short-circuit at the top of `get_cached_branch_schema()` and `get_cached_graphql_sdl()` so they fall back to direct SDK calls (preserving existing behaviour) when `app_ctx.config.schema_cache_enabled` is False. (Most behaviour already wired through T002 + the helpers; this task makes it explicit and tested.)

**Checkpoint**: US5 GREEN. Operators can opt out without code changes.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T046 In `src/infrahub_mcp/middleware.py`, modify `configure_middleware()` so that when `cache_enabled=True`, schema URIs (`infrahub://schema`, `infrahub://schema/{kind}`, `infrahub://graphql-schema`) and the `get_schema` tool are excluded from `ResponseCachingMiddleware`. The new schema cache owns correctness for these endpoints; other resources/tools keep their middleware caching.
- [ ] T047 [P] End-to-end middleware-exclusion test in `tests/unit/test_middleware.py` (or extend the existing test file): with caching enabled, calling `read_resource("infrahub://schema")` does NOT register a hit in the FastMCP cache statistics, while calling a non-schema cached resource still does.
- [ ] T048 [P] Add a brief section to `dev/knowledge/architecture.md` describing the schema-cache layer: purpose, lifetime, invalidation model, interaction with `ResponseCachingMiddleware`. One short paragraph + link to `specs/20260504-203256-schema-cache/`.
- [ ] T049 [P] Add operator-facing documentation for the four new `INFRAHUB_MCP_SCHEMA_CACHE_*` environment variables under `docs/docs/` if a runtime-config reference page exists; otherwise skip.
- [ ] T050 Run `uv run invoke format` to auto-format the changes.
- [ ] T051 Run `uv run invoke lint` and ensure ruff, pylint (10.00/10), mypy (0 issues), yamllint are all clean.
- [ ] T052 Run `uv run pytest` and confirm 0 failures, target ≥ 325 passed (existing baseline) plus the new tests added in this feature.
- [ ] T053 Open upstream PR against `infrahub-sdk-python` adding `client.schema.summary(branch=None) -> SchemaBranchHash`. Link the issue/PR URL into a `# TODO` comment near the `client._get()` call site so it's easy to find when swapping later.
- [ ] T054 Commit on `feat/schema-cache` and push; open a draft PR titled `feat(schema-cache): hash-validated schema cache for passthrough modes` referencing the spec file.

---

## Dependencies

- **Phase 1** → **Phase 2** (foundational types)
- **Phase 2** → **Phase 3** (US1 cannot start without `CachedSchemaEntry` + `AppContext` fields + config)
- **Phase 3** is the smallest shippable unit but is unsafe alone without correctness — the MVP is **Phase 3 + Phase 4 (US1 + US2)**.
- **Phase 5** depends on Phase 4 (circuit-break logic operates on revalidation counters introduced in US2 path).
- **Phase 6** depends on Phase 3+4+5 implementations existing so counters can be wired into them.
- **Phase 7** is mostly verification + a small early-return; depends on Phase 3.
- **Phase 8** depends on all earlier phases.

## Parallel-execution opportunities

- T002 / T003 / T004 are in different files → run in parallel.
- T012 / T013 / T014 / T015 / T016 are call-site refactors in different files → run in parallel after T009–T011 land.
- All test files within a phase are `[P]` — write the test bodies in parallel.

## MVP scope

- **MVP**: Phase 1 + Phase 2 + Phase 3 (US1) + Phase 4 (US2) + Phase 8's lint/format/test polish (T050–T052) + Phase 8's middleware carve-out (T046).
- **Production-ready**: MVP + Phase 5 (US3) + Phase 6 (US4) + Phase 7 (US5) + remaining polish.

## Format validation

All tasks above conform to `- [ ] T### [P?] [Story?] Description with file path` per `tasks-template.md`. Setup, foundational, and polish tasks omit the `[Story]` label as specified.
