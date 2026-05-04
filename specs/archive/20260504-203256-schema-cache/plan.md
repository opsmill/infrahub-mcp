# Implementation Plan: Hash-Validated Schema Cache

**Branch**: `feat/schema-cache` | **Date**: 2026-05-04 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/20260504-203256-schema-cache/spec.md`

## Summary

Introduce a process-wide, hash-validated schema cache for the Infrahub MCP server. In passthrough auth modes (`token-passthrough`, `basic-passthrough`) `get_client()` builds a fresh `InfrahubClient` per request, discarding the SDK's per-client schema cache; this feature reinstates cross-request caching at a layer above the SDK by storing `BranchSchema` and GraphQL SDL on `AppContext`, gated by the upstream schema hash returned from the existing `GET /api/schema/summary` endpoint. The cache is correctness-preserving (skip-window TTL → cheap hash check → full refetch only on hash mismatch) and resilience-aware (serve-stale on transient failures, fail-closed once configured circuit-break thresholds are crossed).

## Technical Context

**Language/Version**: Python 3.13
**Primary Dependencies**: `infrahub-sdk` (existing), `fastmcp` (existing), `pydantic-settings` (existing). No new runtime dependencies.
**Storage**: In-memory only. Cache lives on `AppContext` (process-wide for the server lifetime). No external store.
**Testing**: `pytest`, `pytest-asyncio`. Unit tests with mocked `InfrahubClient`; concurrency single-flight test via `asyncio.gather`.
**Target Platform**: Linux server (single-process MCP server). Multi-replica deployments out of scope (FR-016).
**Project Type**: Internal infrastructure feature in an existing single-project Python package (`src/infrahub_mcp/`).
**Performance Goals**: SC-001/SC-006: zero upstream schema-body transfer on cache-hit paths within the skip-window. SC-003: single upstream fetch under 10-coroutine cold-cache burst. SC-004: ≥90 % cache-hit ratio in steady state.
**Constraints**:
- Passthrough modes only (FR-001); other auth modes already benefit from SDK-level cache and remain untouched.
- Cache key by branch only (FR-002, FR-017) — schema is global per branch.
- No new runtime dependencies (Constitution Principle VII).
- The Infrahub SDK exposes no public wrapper for `GET /api/schema/summary` yet; the implementation calls `client._get()` directly with a `# noqa: SLF001` and a `TODO` mirroring the existing pattern in `resources/schema.py:79` (graphql_schema). Upstream PR adding `client.schema.summary()` is a planned follow-up.
**Scale/Scope**: Up to a few hundred branches per server in realistic deployments. ~30 KB to a few MB per cached `BranchSchema` (negligible memory footprint). No bounded LRU; relies on operator awareness for unusual branch-explosion scenarios.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Evaluated against `dev/constitution.md` v1.0.0:

| Principle | Verdict | Rationale |
|---|---|---|
| I. MCP Protocol Compliance | PASS | No new tools/resources/prompts; the cache is internal. Existing schema resources continue to expose the same MCP contract. |
| II. Infrahub SDK Integration | PASS w/ noted exception | All schema fetches go through `client.schema._fetch()` and `client.schema.set_cache()`. The hash-summary call uses `client._get()` because the SDK does not yet expose a public `client.schema.summary()`; the existing code already does this for the GraphQL SDL fetch. **Mitigation:** open upstream PR adding `client.schema.summary()` and swap when released. |
| III. Branch-Safe by Default | PASS | Read-only feature. No write paths added. |
| IV. Type Safety & Explicit Contracts | PASS | Full type annotations on all new module surfaces. New `ServerConfig` fields use `pydantic-settings`. No `Any` at public interfaces. The `(BranchSchema, hash, fetched_at, consecutive_failures)` cache value uses a frozen pydantic model or `dataclass(frozen=True)`. |
| V. Test Discipline | PASS | TDD via `superpowers:test-driven-development` skill. Unit tests for every cache state transition; concurrency single-flight test; F1/F2/F3 error paths. Test file mirrors source: `tests/unit/test_schema_cache.py`. |
| VI. Security & Input Boundaries | PASS | Cache is global per branch, identical for any authenticated user (assumption from spec, validated against current Infrahub schema-permission model). FR-008 explicitly justifies serving-stale on auth errors as non-leaking because schema metadata isn't user-protected. No credentials cached or logged. |
| VII. Simplicity & Maintainability | PASS | Single new module (`schema_cache.py`). Three new `ServerConfig` fields. No new dependencies. Reuses existing `AppContext` + `asyncio.Lock` pattern (already used for `default_branch`). |

**Initial gate: PASS — proceeding to Phase 0.**

(Re-evaluate after Phase 1 design.)

## Project Structure

### Documentation (this feature)

```text
specs/20260504-203256-schema-cache/
├── plan.md              # This file
├── spec.md              # Feature specification (clarified)
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
└── checklists/
    └── requirements.md  # Spec quality checklist
```

No `contracts/` subdirectory — this is an internal feature; the only external interface affected is the existing `/metrics` endpoint (FR-012) and existing schema MCP resources whose URIs and semantics do not change.

### Source Code (repository root)

```text
src/infrahub_mcp/
├── schema_cache.py          # NEW — cache logic, helper API
├── utils.py                 # MODIFIED — AppContext gains cache fields
├── config.py                # MODIFIED — ServerConfig gains 4 new fields
├── middleware.py            # MODIFIED — strip schema URIs from ResponseCachingMiddleware
├── metrics.py               # MODIFIED — register new aggregate counters
├── schema.py                # MODIFIED — call sites in get_schema_catalog/detail use cache helpers
├── resources/
│   └── schema.py            # MODIFIED — graphql_schema resource uses cache helper
└── tools/
    ├── nodes.py             # MODIFIED — 3 call sites for client.schema.get(...)
    ├── schema.py            # MODIFIED — get_schema tool uses cache helper
    └── write.py             # MODIFIED — 2 call sites for client.schema.get(...)

tests/
└── unit/
    └── test_schema_cache.py # NEW — full cache behaviour coverage
```

**Structure Decision**: Existing single-project layout under `src/infrahub_mcp/`. The new file is a sibling of `schema.py` (which holds the post-processing helpers) and `utils.py` (which holds `AppContext`). This separates the "decide when to fetch" concern (`schema_cache.py`) from "transform a fetched schema into payloads" (`schema.py`).

## Phase 0: Outline & Research

See [research.md](./research.md). All open questions from the brainstorm and `/speckit-clarify` session are resolved; the remaining research surface is verifying upstream behaviour and confirming the SDK's cache-injection contract works as expected in passthrough mode.

## Phase 1: Design & Contracts

See [data-model.md](./data-model.md) for entity shapes (cache value, snapshot key, circuit-break state). See [quickstart.md](./quickstart.md) for the operator-facing "how do I verify this works" walkthrough.

No formal `contracts/` directory: the only external surface that changes is the `/metrics` endpoint (additive — new counter names). The schema MCP resources keep their existing URIs and response shapes.

## Phase 2 (deferred to /speckit-tasks)

Tasks generation will produce a vertical-slice TDD task list that maps each user story (P1 first) to:
1. Failing test
2. Minimum implementation
3. Refactor pass + lint/type-check
4. Constitution Principle V verification

`/speckit-tasks` is the next command after this plan is reviewed.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|---|---|---|
| `client._get(/api/schema/summary)` (Principle II partial bypass) | The Infrahub SDK does not yet expose a public `client.schema.summary()` wrapper, even though the server endpoint exists. Without this call we cannot detect schema staleness cheaply. | Filing the upstream PR alone defers shipping by an SDK release cycle. The existing `resources/schema.py:79` graphql_schema resource already uses `client._get()` with the same justification, so this is a precedent rather than a new violation. **Follow-up**: open SDK PR; swap once landed. |

No other deviations from the constitution.
