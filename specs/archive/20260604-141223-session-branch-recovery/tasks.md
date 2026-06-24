---
description: "Task list for Session Branch Recovery & Reset"
---

# Tasks: Session Branch Recovery & Reset

**Input**: Design documents from `specs/20260604-141223-session-branch-recovery/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/mcp-tools.md
**Tests**: INCLUDED — required by FR-009 / SC-004 and explicitly requested. TDD per Constitution V (write tests first, see them fail).
**Branch**: `feat/session-branch-recovery`

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 / US2 / US3 (Setup, Foundational, Polish carry no story label)

## Path Conventions

Single project: `src/infrahub_mcp/`, `tests/unit/` at repo root.

---

## Phase 1: Setup (Shared Infrastructure)

- [x] T001 Verify baseline before changes: `uv sync` then `uv run pytest tests/unit/test_session_branch_validation.py` is green (repo root).
- [x] T002 [P] Create test module skeleton `tests/unit/test_reset_session_branch.py` — imports, pytest-asyncio, and a `_make_ctx(app_ctx, session=None)` helper whose `ctx.request_context.session` returns a stable per-session object (so `WeakKeyDictionary` keying works in tests).

---

## Phase 2: Foundational (Blocking Prerequisites)

**⚠️ CRITICAL**: every user story touches session-branch state — this phase must complete first. Includes the breaking `AppContext` change (critique E3).

- [x] T003 Refactor `AppContext` in `src/infrahub_mcp/utils.py`: remove `session_branch` and `_session_branch_lock`; add `import weakref`; add `_session_branches: WeakKeyDictionary[Any, str]`, `_session_locks: WeakKeyDictionary[Any, asyncio.Lock]`, and `_session_locks_guard: asyncio.Lock` (keep `default_branch`/`_default_branch_lock` unchanged).
- [x] T004 Add helpers in `src/infrahub_mcp/utils.py`: `_session_obj(ctx)` (returns `ctx.request_context.session`, raising the existing error when absent), async `_get_session_lock(app_ctx, sess)` (lazy per-session lock created under `_session_locks_guard`), and `get_session_branch(ctx)` (no-create reader: `app_ctx._session_branches.get(_session_obj(ctx))`). Depends on T003.
- [x] T005 Migrate readers off the removed field: `get_session_info` in `src/infrahub_mcp/tools/session.py` and `propose_changes` in `src/infrahub_mcp/tools/write.py` (lines ~275–306) to read via `get_session_branch(ctx)`; update the `get_session_info` docstring to per-session wording. Depends on T004.
- [x] T006 Update existing tests in `tests/unit/test_session_branch_validation.py` to the new state model: seed/inspect state via `_session_branches[session]` and the new helpers instead of the `session_branch=` kwarg, preserving the deleted-branch recovery, cached-reuse, and first-write assertions (regression). Depends on T004.

**Checkpoint**: state model compiles, suite runs, deleted-branch recovery still passes.

---

## Phase 3: User Story 1 - Auto-recover after merge/read-only (Priority: P1) 🎯 MVP

**Goal**: Writes succeed on a fresh branch after the session branch is merged/deleting, without a server restart; the swap is reported (old→new). Closes symptoms #1 and #3 and the TOCTOU window (FR-011).

**Independent Test**: Cache a branch whose `branch.get()` returns `status=MERGED`; issue a write; assert it succeeds on a new branch and the old/new names are logged — no restart.

### Tests for User Story 1 (write first, see fail)

- [x] T007 [P] [US1] Parametrized recovery tests in `tests/unit/test_session_branch_validation.py`: cached branch with `status` MERGED and DELETING → entry cleared, new branch created, `ctx.warning` names old + new.
- [x] T008 [P] [US1] Reuse tests in `tests/unit/test_session_branch_validation.py`: `status` OPEN and NEED_REBASE → cached branch reused, `branch.create` not called.
- [x] T009 [P] [US1] Per-session isolation test in `tests/unit/test_session_branch_validation.py`: recovery for session A leaves session B's `_session_branches` entry unchanged (two distinct session objects).
- [x] T010 [P] [US1] FR-011 reactive-net tests in `tests/unit/test_reset_session_branch.py`: a write raising a read-only/`has been merged` `GraphQLError` clears the session entry and raises a retryable `ToolError`; parametrize node_upsert / node_delete / mutate_graphql.

### Implementation for User Story 1

- [x] T011 [US1] In `src/infrahub_mcp/utils.py`: import `BranchStatus` from `infrahub_sdk.branch` and define `_UNWRITABLE_STATUSES = {BranchStatus.MERGED, BranchStatus.DELETING}`.
- [x] T012 [US1] Extend `get_or_create_session_branch` in `src/infrahub_mcp/utils.py`: key by `_session_obj` + per-session lock; on a cached entry, inspect `branch.get().status` and recover (clear entry, recreate, `ctx.warning` old→new) for `_UNWRITABLE_STATUSES`, in addition to the existing `BranchNotFoundError` path. Depends on T011.
- [x] T013 [US1] Implement the FR-011 reactive net in `src/infrahub_mcp/tools/write.py`: a small helper that catches read-only/merged `GraphQLError` from SDK writes, clears the calling session's entry, and raises a retryable `ToolError`; apply it in `node_upsert`, `node_delete`, and `mutate_graphql` (default-branch path). Depends on T012.

**Checkpoint**: US1 fully functional — the customer's reported bug is fixed.

---

## Phase 4: User Story 2 - Manual reset of the session branch (Priority: P2)

**Goal**: An operator can drop the session's branch so the next write provisions a fresh one.

**Independent Test**: With a cached branch, call `reset_session_branch()`; assert the entry is cleared and the next `get_or_create_session_branch` creates a new branch.

### Tests for User Story 2

- [x] T014 [P] [US2] Tests in `tests/unit/test_reset_session_branch.py`: `reset_session_branch()` (no arg) clears the entry and returns `action="reset"`, `session_branch=null`; calling it with nothing cached is a safe no-op.
- [x] T015 [P] [US2] Reset-isolation test in `tests/unit/test_reset_session_branch.py`: reset in session A does not affect session B's entry.

### Implementation for User Story 2

- [x] T016 [US2] Implement `reset_session_branch(ctx, branch: str | None = None)` in `src/infrahub_mcp/tools/write.py`, tagged `{"session", "write"}`, `ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=False)`; implement the `branch=None` path (clear this session's entry) and return the documented dict. Mounted via `write_mcp` (auto-hidden in read-only mode).
- [x] T017 [US2] Update the write-mode system prompt in `src/infrahub_mcp/server.py` (`infrahub_agent`) to document `reset_session_branch` and when to use it (reset vs. switch vs. create).

**Checkpoint**: US1 + US2 both work independently.

---

## Phase 5: User Story 3 - Switch/override to an explicitly named branch (Priority: P3)

**Goal**: Point the session at a named branch; create it when the name conforms to `branch_pattern`, else an actionable error. Closes symptom #2.

**Independent Test**: `reset_session_branch(branch="<conformant-missing-name>")` creates and switches; a non-conformant name errors and creates nothing; `main` is rejected.

### Tests for User Story 3

- [x] T018 [P] [US3] Parametrized `branch_name_conforms` tests in `tests/unit/test_session_branch_validation.py` (or a new `tests/unit/test_branch_conformance.py`): conformant vs non-conformant names, adjacent-placeholder cases, `{user}`-with-`/`, and fixed-pattern exact match.
- [x] T019 [P] [US3] Tool tests in `tests/unit/test_reset_session_branch.py`: switch to existing writable non-default branch (`action="switched"`); missing + conformant → created + `created=true`; missing + non-conformant → `ToolError`, nothing created; default branch → reject; existing merged/read-only target → `ToolError`.

### Implementation for User Story 3

- [x] T020 [US3] Implement `branch_name_conforms(name, pattern)` in `src/infrahub_mcp/utils.py`: regex via `string.Formatter().parse(pattern)` + `re.escape` literals + non-greedy placeholder classes (`{date}=\d{8}`, `{hex}=[0-9a-f]{8}`, `{user}=[A-Za-z0-9._/-]+?`), anchored; fixed pattern → exact match; plus allowed-charset check (reuse `auth` rules).
- [x] T021 [US3] Extend `reset_session_branch` in `src/infrahub_mcp/tools/write.py` to handle a provided `branch`: `assert_writable_branch` (reject default); `branch.get()` → exists+writable → switch (`action="switched"`); `BranchNotFoundError` + conformant → create + switch + inform (`action="created"`); not conformant → `ToolError`; `status ∈ _UNWRITABLE_STATUSES` → `ToolError`. Depends on T016, T020.

**Checkpoint**: all three user stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T022 [P] Add user documentation in `docs/docs/` covering auto-recovery and `reset_session_branch` (reset/switch/create + the conformance rule and branch-sprawl note, critique P4); run `uv run rumdl check docs/docs/`.
- [x] T023 [P] Update `dev/knowledge/` (architecture): per-session branch scoping via `WeakKeyDictionary` + proactive `status` detection + FR-011 reactive net.
- [x] T024 [P] Add a `dev/adr/` entry recording the decisions: per-session scoping (vs process-wide), proactive `BranchData.status` detection, and the required reactive net.
- [x] T025 Verify recovery/switch events are captured by the audit trail (critique P5) — confirm the audit middleware in `src/infrahub_mcp/middleware.py` records old→new branch swaps, not just a transient `ctx.warning`; extend if needed.
- [x] T026 Run full quality gates from repo root: `uv run invoke format lint` (ruff, mypy, pylint, yamllint) and `uv run pytest`; resolve all findings (mypy-clean, no `Any` at public interfaces).
- [x] T027 Verify live behavior against a running Infrahub. Done as a repeatable, skip-guarded integration suite `tests/integration/test_live_session_branch.py` (drives the tools via FastMCP's in-memory Client + raw SDK for merge/delete setup): merged-branch recovery (the customer bug, end-to-end), deleted-branch recovery, reset/switch/create + reject-default, and privileged-mutation block. All 4 pass against Infrahub 1.9.6; instance left clean (no residue); skipped without INFRAHUB_ADDRESS.

---

## Phase 7: Write-Authorization Hardening (added after code-review; FR-012 / FR-013)

**Goal**: Confine writes to the session branch and close the default-branch escape via `mutate_graphql`.

- [x] T028 Pin `mutate_graphql` to the session branch in `src/infrahub_mcp/tools/write.py`: remove the per-call `branch` parameter and the explicit-branch path; always resolve via `get_or_create_session_branch`; reactive net always applies. Drop now-unused `assert_writable_branch`/`get_default_branch` imports.
- [x] T029 Add `_assert_no_privileged_mutations` in `src/infrahub_mcp/tools/write.py`: parse the query AST and reject branch-management (`Branch*`) and schema (`SchemaDropdown*`/`SchemaEnum*`) mutations; call it at the top of `mutate_graphql`.
- [x] T030 Harden the explicit-branch path in `reset_or_switch_session_branch` (`src/infrahub_mcp/utils.py`): reject a resolved branch whose `is_default` is true (not just a name compare).
- [x] T031 Tests in `tests/unit/test_reset_session_branch.py`: privileged-mutation guard (blocked Branch*/Schema*, allowed node mutation, invalid syntax), `is_default` rejection; update existing switch/merged mocks to set `is_default`. Docs: `methods.mdx` (mutate_graphql param removal + block note), ADR 0007 hardening section, spec FR-012/FR-013.

**Checkpoint**: writes cannot escape the session branch; `BranchMerge`/schema mutations rejected; review gate cannot be bypassed.

---

## Phase 8: Code-Review Fixes (multi-agent review, 43 verified findings)

- [x] T032 Fix CONFIRMED-high findings: (a) `_maybe_recover_read_only` now confirms branch status via `client.branch.get()` before clearing — no false-positive orphaning on read-only *attribute* errors (new `recover_if_session_branch_stale`, clears under the session lock); (b) `_assert_no_privileged_mutations` scans field names recursively (inline fragments / fragment definitions) and rejects non-mutation operations, closing the `... on Mutation { BranchMerge }` bypass. Plus MED: `{user}` regex no longer spans `/` separators; `branch.create` in reset is guarded; removed dead `clear_session_branch`. New regression tests for each; docs/ADR updated.

**Checkpoint**: review findings resolved; full suite green (369 passed).

---

## Dependencies & Execution Order

### Phase order

- **Setup (P1)** → **Foundational (P2, BLOCKS all stories)** → **US1 → US2 → US3** (priority order) → **Polish (P6)**.
- Decision: built as one whole deliverable (per the "keep it whole" choice), but stories remain independently testable at each checkpoint.

### Cross-task dependencies

- T004 → T003; T005 → T004; T006 → T004.
- T012 → T011; T013 → T012.
- T016 → T004; T021 → T016 + T020.
- All US tests (T007–T010, T014–T015, T018–T019) depend only on the Foundational phase + their helper module.
- Polish T026 depends on all implementation tasks; T025 depends on T012/T013/T016/T021.

### Within each story

- Tests (Tnnn) written first and failing → then implementation → checkpoint.

## Parallel Opportunities

- **Setup**: T002 ‖ (T001 first).
- **US1 tests**: T007 ‖ T008 ‖ T009 ‖ T010 (T007–T009 share one file — coordinate or write as one PR commit; T010 is a different file → safe [P]).
- **US2 tests**: T014 ‖ T015. **US3 tests**: T018 ‖ T019.
- **Polish docs**: T022 ‖ T023 ‖ T024 (different files).

## Parallel Example: User Story 1

```bash
# After Foundational completes, write US1 tests together (then watch them fail):
Task: "Recovery tests (MERGED/DELETING) in tests/unit/test_session_branch_validation.py"   # T007
Task: "Reuse tests (OPEN/NEED_REBASE) in tests/unit/test_session_branch_validation.py"      # T008
Task: "Per-session isolation test in tests/unit/test_session_branch_validation.py"          # T009
Task: "FR-011 reactive-net tests in tests/unit/test_reset_session_branch.py"                # T010
```

## Implementation Strategy

### MVP (User Story 1)

1. Setup + Foundational.
2. US1 (auto-recovery + FR-011). **STOP & VALIDATE** — this alone fixes the customer's reported bug (the merged-branch wedge).

### Incremental delivery

US1 (MVP) → US2 (manual reset) → US3 (named-branch switch/create) → Polish. Each checkpoint is independently testable; later stories don't break earlier ones.

## Notes

- `[P]` = different files, no incomplete dependency. Several US1 test tasks touch the same file — land them as one commit or serialize.
- TDD: confirm each test fails before implementing.
- Per Constitution V, tests are atomic + parametrized; imports at top; `pytest-asyncio`.
- Pre-push (user rule): run linters + a code review before commit/push; never commit to `stable`.
- Branch-sprawl (critique P4): auto-create-on-conformant is intentional; documented in T022 rather than capped.
