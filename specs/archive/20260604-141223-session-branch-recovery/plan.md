# Implementation Plan: Session Branch Recovery & Reset

**Branch**: `feat/session-branch-recovery` | **Date**: 2026-06-04 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/20260604-141223-session-branch-recovery/spec.md`

## Summary

Close the two remaining gaps in session-branch handling left open after PR #110:

1. **Auto-recover** writes when the cached session branch is no longer writable — not just *deleted* (`BranchNotFoundError`, already handled) but also *merged / being deleted*. Detect proactively via `BranchData.status` on the `branch.get()` call the code already makes (zero extra round-trip), clear the cache, recreate, and warn naming old→new branch.
2. **Reset / override** the session branch via one new write-tagged tool `reset_session_branch(branch=None)`, and **scope the session branch per MCP session** (`ctx.session_id`) instead of process-wide, so reset/recovery never disturbs other sessions. Targeting a non-existent name is allowed only when it conforms to the configured `branch_pattern` (then created + reported), else an actionable error.

Implementation is concentrated in `utils.py` (state model + recovery + helpers), `tools/write.py` (new tool + `propose_changes` reader), and `tools/session.py` (session-aware read), with extended unit tests.

## Technical Context

**Language/Version**: Python 3.13.5
**Primary Dependencies**: fastmcp 3.2.4, infrahub-sdk 1.20.0, pydantic 2 / pydantic-settings, Starlette
**Storage**: N/A (in-memory session state on `AppContext`)
**Testing**: pytest + pytest-asyncio (`tests/unit/`), AsyncMock of the SDK client
**Target Platform**: Python MCP server (stdio + streamable-HTTP transports)
**Project Type**: Single project (MCP server library) — `src/infrahub_mcp/`
**Performance Goals**: No added round-trips on the hot write path (status check reuses the existing `branch.get()`); per-session locking must not serialize unrelated sessions
**Constraints**: Recovery without server restart; per-session isolation; per-session state auto-released at session end (no unbounded growth); never write to the default branch; mypy-clean, no `Any` at public interfaces
**Scale/Scope**: Small, focused change — ~3 source files + tests + docs/ADR. No new dependencies.

### Resolved unknowns (see [research.md](./research.md))

- **Detection** → proactive via `BranchData.status ∈ {MERGED, DELETING}` (+ existing `BranchNotFoundError`). Reactive `read-only`/`has been merged` error catch is **required** for the TOCTOU window (FR-011): clear the cached branch + raise a retryable error; never blindly replay an arbitrary mutation.
- **Per-session storage** → `WeakKeyDictionary` keyed by the session object (`ctx.request_context.session`) on the shared `AppContext` — auto-evicts at session end (no leak; critique E1), correct regardless of lifespan scope. `ctx.session_id` used only for display.
- **Conformance** → regex derived from `branch_pattern` via `string.Formatter().parse` + `re.escape` + non-greedy classes (critique E4).

## Constitution Check

*GATE: must pass before Phase 0 (done) and re-checked after Phase 1 design (done — still passing).*

| Principle | Status | Notes |
|---|---|---|
| I. MCP Protocol Compliance | ✅ | New tool registered via existing `write_mcp` composition; tagged `"write"`; standard `ToolError` messages, no internal leakage. |
| II. Infrahub SDK Integration | ✅ | All branch ops via `client.branch.*` (`get`, `create`); no raw HTTP. |
| III. Branch-Safe by Default | ✅ | `assert_writable_branch` reused for explicit target; default branch never written; explicit names validated against `branch_pattern` + allowed charset. |
| IV. Type Safety & Explicit Contracts | ✅ | Full annotations; `dict[str, str]` / `str \| None`; no `Any` at public interfaces; mypy gate. |
| V. Test Discipline | ✅ | Extend `tests/unit/test_session_branch_validation.py` + new tool test module; parametrized; pytest-asyncio. |
| VI. Security & Input Boundaries | ✅ | Tool input validated (charset + conformance) before SDK; no secrets/internals in errors; per-request client unchanged. |
| VII. Simplicity & Maintainability | ⚠️→✅ | Per-session `dict` adds minor state vs a scalar, but is **required** by FR-010 and is the simplest design satisfying it; status check reuses the existing call. No new dependency, no new abstraction layer. |

**Gate result: PASS — no violations.** Complexity Tracking table not required.

> Architecture/UX changes trigger constitution doc duties: the per-session scoping change updates `dev/knowledge/` and warrants a short `dev/adr/` entry; the new tool is user-facing → `docs/docs/`. These are enumerated as tasks in `/speckit-tasks`. AGENTS.md flags "modifying per-request state model" as *Ask First* — confirm the per-session approach with a maintainer at PR time.

## Project Structure

### Documentation (this feature)

```text
specs/20260604-141223-session-branch-recovery/
├── plan.md            # this file
├── spec.md
├── research.md        # Phase 0
├── data-model.md      # Phase 1
├── quickstart.md      # Phase 1
├── contracts/
│   └── mcp-tools.md   # Phase 1
└── checklists/
    └── requirements.md
```

### Source Code (repository root)

```text
src/infrahub_mcp/
├── utils.py              # AppContext state model; get_or_create_session_branch (status check + per-session key);
│                         #   NEW: _session_obj, _get_session_lock, get_session_branch, clear_session_branch, branch_name_conforms, _UNWRITABLE_STATUSES
├── tools/
│   ├── write.py          # NEW reset_session_branch tool; propose_changes → session-aware reader
│   └── session.py        # get_session_info → session-aware reader
└── (config.py, auth.py, server.py — read/reuse only; auth charset rules reused)

tests/
└── unit/
    ├── test_session_branch_validation.py   # extend: merged/deleting recovery, per-session keying
    └── test_reset_session_branch.py        # NEW: reset/switch/create/error/reject/isolation

docs/docs/ (+ dev/knowledge/, dev/adr/)     # user doc + architecture note + ADR
```

**Structure Decision**: Single-project layout (existing `src/infrahub_mcp/`). Changes localize to the three files that touch session-branch state; all write tools inherit recovery via the shared `get_or_create_session_branch`.

## Phase 0 — Outline & Research

Complete. See [research.md](./research.md): R1 detection mechanism, R2 per-session identity + lifespan-scope ambiguity, R3 conformance validation, R4 tool placement/tagging. All `NEEDS CLARIFICATION` resolved.

## Phase 1 — Design & Contracts

Complete:

- [data-model.md](./data-model.md) — `AppContext` map model, session-key value object, writability classification (`status`), conformance rule, state transitions, touched readers.
- [contracts/mcp-tools.md](./contracts/mcp-tools.md) — `reset_session_branch` I/O + error matrix; behavioral deltas for `get_or_create_session_branch`, `get_session_info`, `propose_changes`.
- [quickstart.md](./quickstart.md) — manual scenarios A–D + verification gates.
- Agent context (`AGENTS.md` SPECKIT block) updated to point at this plan.

### Implementation outline (for `/speckit-tasks`)

1. **State model** (`utils.py`): **remove** the `session_branch` field + `_session_branch_lock` (breaking change — migrate all readers and the existing tests, critique E3). Add `_session_branches`/`_session_locks` as `WeakKeyDictionary` keyed by the session object + `_session_locks_guard`. Add `_session_obj(ctx)`, a `_get_session_lock` helper, and `get_session_branch(ctx)`.
2. **Recovery** (`utils.py` + write paths): in `get_or_create_session_branch`, key by `_session_obj`; add `_UNWRITABLE_STATUSES = {MERGED, DELETING}`; on a cached entry, inspect `branch.get().status` and recover (warn old→new) in addition to `BranchNotFoundError`. Add the **required** FR-011 reactive net on `node_upsert`/`node_delete`/`mutate_graphql` (default path): catch read-only/merged `GraphQLError` → clear the session entry → raise a retryable `ToolError`.
3. **Conformance helper** (`utils.py`): `branch_name_conforms(name, pattern)` (regex from pattern + charset check).
4. **New tool** (`tools/write.py`): `reset_session_branch(branch=None)` tagged `{"session","write"}`; implement the error matrix from the contract; reuse `assert_writable_branch`, `get_default_branch`, branch-create helpers.
5. **Session-aware readers**: `get_session_info` (session.py) and `propose_changes` (write.py) read via `get_session_branch(ctx)`. Update the system prompt in `server.py` to mention `reset_session_branch`.
6. **Tests**: extend + new module per quickstart (TDD — write failing tests first).
7. **Docs/ADR**: user doc for the tool; `dev/knowledge/` architecture note; short ADR on per-session scoping + proactive status detection.

## Complexity Tracking

No constitution violations — table intentionally omitted.
