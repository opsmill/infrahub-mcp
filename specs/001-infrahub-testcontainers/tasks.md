# Tasks: Infrahub Testcontainers Integration Tests

**Input**: Design documents from `/specs/001-infrahub-testcontainers/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/, quickstart.md

**Tests**: This feature's deliverable **is** the integration test suite. The test files in Phase 3 ARE the implementation (not a separate test-first layer). Foundational fixtures (Phase 2) are the harness those tests depend on.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

> **Implementation status (2026-06-15)**: MVP (Phases 1–3, T001–T017) implemented; default unit suite verified green (`328 passed, 12 deselected`) and integration tests verified to collect (12 tests, asyncio). The Docker end-to-end run (T018) and Phases 4–6 (US2/US3/Polish) are **not yet done** — see the report. Code written but the live Infrahub container run is deferred.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- Exact file paths are included in each description

## Path Conventions

Single project. Source under `src/infrahub_mcp/`, tests under `tests/` at repo root. New work lives in `tests/integration/`, `pyproject.toml`, `.github/workflows/ci.yml`, and `docs/docs/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add the dependency and configure suite separation so the default loop stays Docker-free.

- [X] T001 Add `infrahub-testcontainers` to the `dev` dependency group in `pyproject.toml`, pinned to a specific minor (e.g. `~=X.Y`), then run `uv sync --all-groups` (research D5; FR-008)
- [X] T002 In `pyproject.toml` `[tool.pytest.ini_options]`: register the `integration` marker, add default selection `-m "not integration"`, and keep `-p no:pytest-infrahub` for the default run (research D6, spec Clarifications; FR-002, SC-002)
- [X] T003 [P] Create the integration package skeleton: `tests/integration/__init__.py` and the `tests/integration/fixtures/` directory (plan Project Structure)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The session container, seed data, per-test branch, and in-process MCP client fixtures every integration test depends on.

**⚠️ CRITICAL**: No user-story test (Phase 3+) can run until this phase is complete.

- [X] T004 [P] Create minimal seed schema `tests/integration/fixtures/schema_minimal.yml`, reusing an existing demo shape (e.g. `LocationSite`) so unit and integration fixtures share a mental model (data-model SeedSchema; research D9)
- [X] T005 [P] Create baseline seed-data loader `tests/integration/fixtures/seed.py` using the Infrahub SDK to create fixed nodes on `main` (data-model SeedNodes; research D9; Constitution II)
- [X] T006 Implement the session-scoped Infrahub container fixture in `tests/integration/conftest.py` via `infrahub-testcontainers`, with Docker-availability fail-fast and an HTTP readiness probe; rely on the upstream per-session project name + random ports for concurrent-run isolation (data-model IntegrationTestSession; research D1, D10; FR-001, FR-007, FR-009; edge cases: Docker-unavailable, slow-startup, image-pull-failure)
- [X] T007 Add session seeding (load `schema_minimal.yml`, then `seed.py` nodes on `main`) to `tests/integration/conftest.py`, gated on container readiness (data-model SeedSchema/SeedNodes; research D9; FR-011)
- [X] T008 Implement the function-scoped per-test Infrahub branch fixture in `tests/integration/conftest.py` (create off `main`, delete in `try/finally`) (data-model PerTestBranch; FR-011, FR-004; Constitution III)
- [X] T009 Implement the in-process FastMCP `mcp_client` fixture in `tests/integration/conftest.py` using `Client(mcp)` (in-memory transport) with the container Infrahub address + admin token via env, `read_only=false` (data-model McpServerUnderTest; research D2)
- [X] T010 Implement guaranteed teardown in `tests/integration/conftest.py`: interruption-safe cleanup of containers/networks/volumes and per-test branches, plus the `INFRAHUB_TESTCONTAINERS_KEEP` opt-out toggle (FR-004; research D8; edge case: Ctrl-C/CI-cancel; SC-005)

**Checkpoint**: Harness ready — integration test files can now be authored. ✅

---

## Phase 3: User Story 1 - Validate MCP server against real Infrahub (Priority: P1) 🎯 MVP

**Goal**: A local integration suite that provisions an ephemeral Infrahub, exercises the MCP surface against it, and reports pass/fail with clean teardown.

**Independent Test**: On a machine with Docker, `uv run pytest -m integration` starts an Infrahub container, runs the tests, tears everything down, and prints a clear pass/fail summary.

> The test files below are independent (separate files) and map to the contracts in `contracts/integration-test-surface.md`. All drive the server via the `mcp_client` in-process fixture.

- [X] T011 [P] [US1] `tests/integration/test_schema_resource.py` — read the `infrahub://schema` resource and assert it includes the seeded kind (contract R1; FR-005)
- [X] T012 [P] [US1] `tests/integration/test_branches_resource.py` — read the `infrahub://branches` resource and assert it includes `main` + the per-test branch, with `main` flagged default (contract R2; FR-005)
- [X] T013 [P] [US1] `tests/integration/test_node_tools.py` — `get_nodes` list + filter + pagination cases against seeded data (contracts T1, T2; FR-005)
- [X] T014 [P] [US1] `tests/integration/test_graphql_tool.py` — `query_graphql` read against seeded shape; assert mutations are rejected as MCP-standard errors (contract T3; FR-005; Constitution I, VI)
- [X] T015 [P] [US1] `tests/integration/test_write_tool.py` — `node_upsert` does not touch `main` (branch-safety); plus a `read_only=true` variant (reloaded server) asserting the write is rejected (contract T4; FR-005; Constitution III, VI)
- [X] T016 [P] [US1] `tests/integration/test_version_compat.py` — read running Infrahub version, assert MAJOR.MINOR matches the pinned `infrahub-sdk`, emit a distinct `xfail` labeled "version drift" on mismatch (contract V1; FR-013; edge case: version-drift)
- [X] T017 [P] [US1] `tests/integration/test_failure_modes.py` — F2: malformed tool input rejected by FastMCP schema enforcement; F1 (weaker, non-destructive): bad request surfaces a clean MCP error with no stack trace (contracts F1, F2; FR-012; Constitution VI)
- [ ] T018 [US1] Verify the full local flow end-to-end via `uv run pytest -m integration`: provisions, runs, tears down with zero residual Docker state, under the 10-minute budget (FR-003, FR-004; SC-001, SC-005; quickstart) — **DEFERRED**: harness verified via `--collect-only` (12 tests) + default unit suite green; the live Docker run is pending (see report's "first-run checklist")

**Checkpoint**: US1 code complete; live validation pending T018.

---

## Phase 4: User Story 2 - Run integration tests in CI (Priority: P2)

**Goal**: CI runs the integration suite on every PR as a distinct, merge-gating check.

**Independent Test**: Open a PR that breaks the MCP↔Infrahub interaction → the CI `integration-tests` job fails and blocks merge.

- [ ] T019 [US2] Add an `integration-tests` job to `.github/workflows/ci.yml`: `ubuntu-latest`, setup uv + Python 3.13, `uv sync --all-groups`, `uv run pytest -m integration --tb=short`, pin `INFRAHUB_TESTING_IMAGE_VER`, reuse the existing `files-changed` path filter (research D4; FR-006, FR-008)
- [ ] T020 [US2] Ensure the CI job surfaces diagnostic context on failure (failing test name, per-test branch, last ~200 lines of `infrahub-server`/`task-worker` logs) in `.github/workflows/ci.yml` (research D7; FR-012)
- [ ] T021 [P] [US2] Document the required-check / branch-protection setup that gates merges to `stable` on the `integration-tests` job (research D4; SC-003)

**Checkpoint**: PRs are validated and gated in CI.

---

## Phase 5: User Story 3 - Keep the fast unit loop intact (Priority: P2)

**Goal**: Default `uv run pytest` stays Docker-free and within 5% of its current runtime.

**Independent Test**: Run the default command → only unit tests run, no containers start, runtime ≈ baseline.

- [ ] T022 [P] [US3] Add `tests/unit/test_integration_separation.py` asserting the default pytest selection collects zero `integration`-marked tests (guards FR-002 / no accidental Docker in the fast loop) (FR-002; US3 AC1)
- [ ] T023 [P] [US3] Measure default `uv run pytest` wall-clock vs the pre-feature baseline, confirm <5% delta, and record the result in `quickstart.md` (SC-002; US3 AC2)

**Checkpoint**: Fast inner loop verified unchanged. (Provisionally confirmed: `1.67s`, 12 deselected.)

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, guidelines, and quality gates spanning all stories.

- [ ] T024 [P] Add a user-facing testing page in `docs/docs/` (Diataxis, `.mdx`) describing the unit vs integration commands and each one's prerequisites (FR-010, SC-006; US3 AC3; Constitution doc requirement)
- [ ] T025 [P] Capture an integration-testing guideline in `dev/guidelines/` (in-process FastMCP client pattern, branch-per-test isolation, fixture lifecycle) (Constitution doc requirement)
- [ ] T026 Run `uv run invoke format lint` and resolve all ruff + mypy findings over `tests/integration/` (Constitution IV; quality gate)
- [ ] T027 Validate `quickstart.md` end-to-end on a clean checkout to confirm first-attempt success (SC-006)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup — **BLOCKS all user stories**.
- **User Stories (Phase 3–5)**: All depend on Foundational. US1 is the MVP; US2 and US3 depend only on the harness + US1's suite existing (US2 runs it in CI; US3 verifies it stays excluded by default).
- **Polish (Phase 6)**: Depends on the desired user stories being complete.

### User Story Dependencies

- **US1 (P1)**: After Foundational. No dependency on other stories.
- **US2 (P2)**: After US1's suite exists (CI runs the integration marker). Independently testable via a deliberately-broken PR.
- **US3 (P2)**: After Setup's marker/addopts (T002); independently testable via the default command. Can proceed in parallel with US1/US2.

### Within Each Story

- Foundational `conftest.py` tasks (T006–T010) are **sequential** — same file.
- US1 test files (T011–T017) are **parallel** — separate files; T018 depends on all of them.
- CI tasks (T019–T020) are **sequential** — same `ci.yml` file.

### Parallel Opportunities

- T003 ∥ T001/T002 boundary (different files; T001→T002 sequential on `pyproject.toml`).
- T004 ∥ T005 (separate fixture files).
- T011–T017 all parallel (separate test files).
- T021, T022, T023, T024, T025 are each `[P]` against their peers (distinct files).

---

## Parallel Example: User Story 1

```bash
# After the Phase 2 harness is in place, author all US1 test files in parallel:
Task: "tests/integration/test_schema_resource.py (R1)"
Task: "tests/integration/test_branches_resource.py (R2)"
Task: "tests/integration/test_node_tools.py (T1, T2)"
Task: "tests/integration/test_graphql_tool.py (T3)"
Task: "tests/integration/test_write_tool.py (T4)"
Task: "tests/integration/test_version_compat.py (V1)"
Task: "tests/integration/test_failure_modes.py (F1, F2)"
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1: Setup (T001–T003) ✅
2. Phase 2: Foundational harness (T004–T010) ✅ — **critical, blocks everything**
3. Phase 3: US1 test files (T011–T017) ✅ + end-to-end verification (T018, deferred)
4. **STOP and VALIDATE**: `uv run pytest -m integration` locally — green, clean teardown. *(pending — needs Docker run)*

### Incremental Delivery

1. Setup + Foundational → harness ready
2. US1 → local integration suite (MVP) → validate
3. US2 → CI gating → validate via broken-PR test
4. US3 → confirm fast loop unaffected
5. Polish → docs, guidelines, lint, quickstart validation

---

## Notes

- The deliverable is tests; Phase 3 files are the product, not a TDD pre-step.
- [P] = different files, no incomplete dependencies. `conftest.py` and `ci.yml` tasks are intentionally not `[P]` (shared files).
- Trace IDs (FR-/SC-/contract R#,T#,V#,F#) are in each task for coverage back to spec.md and contracts/.
- SC-004 (catch a real drift within a quarter) is a post-launch observational outcome, not a buildable task — validated in production, not in this plan.
- Commit after each task or logical group; keep `tests/unit/` untouched except the T022 separation guard (Phase 5, not yet done).
- **Implementation deviation**: the harness imports `infrahub_testcontainers` classes directly and does not require the `pytest-infrahub` plugin to be enabled (both infrahub pytest plugins are disabled in `addopts` for all runs). This is simpler than research D6 anticipated; spec FR-002's "plugin enabled for integration" is satisfied-by-not-needed.
