---
description: "Task list for graph traversal tools + single-level schema expansion"
---

# Tasks: Graph Traversal Tools + Single-Level Schema Expansion

**Input**: Design documents from `specs/002-traversal-tools/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/tools.md

**Tests**: Included — the spec requires offline unit coverage (SC-005). New unit tests mock the SDK.

**Detailed code**: Every step's full code + exact commands are in `docs/superpowers/plans/2026-06-24-traversal-tools.md`. This file is the dependency-ordered index.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency)
- **[Story]**: US1 = find_paths, US2 = find_reachable, US3 = single-level schema expansion

## Path Conventions

Single project: `src/infrahub_mcp/`, `tests/unit/` at repo root.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: dependency floor required by all traversal work.

- [ ] T001 Raise SDK floor to `infrahub-sdk>=1.22.0` in `pyproject.toml`; `uv sync`; verify `from infrahub_sdk.graph_traversal import PathTraversalResult, ReachableNodesResult` imports. Commit.

**Checkpoint**: Traversal SDK API importable.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: config + schema changes both stories and the schema story build on. Independent of each other ([P]).

- [ ] T002 [P] [US3] Replace `max_query_depth` with boolean `schema_expand_peers` (env `INFRAHUB_MCP_SCHEMA_EXPAND_PEERS`, default true) in `src/infrahub_mcp/config.py`; rewrite `tests/unit/test_config.py` (parametrized true/false parsing + invalid). TDD. Commit.
- [ ] T003 [P] [US3] Collapse `get_schema_detail` to single non-recursive level (`expand_peers: bool = True`) in `src/infrahub_mcp/schema.py`; delete `_expand_peer_schemas` and recursion/`@ref`/cycle code; add `_build_peer_schema`. Create `tests/unit/test_schema_expand.py`; delete `tests/unit/test_schema_depth.py`. TDD. Commit.

**Checkpoint**: Config + schema core ready.

---

## Phase 3: User Story 3 - Single-level schema authoring helper (Priority: P3)

**Goal**: schema tool + resource honor the boolean toggle.
**Independent Test**: `get_schema(kind=...)` inlines one peer level; `expand=False` flattens; resource honors `INFRAHUB_MCP_SCHEMA_EXPAND_PEERS`.

- [ ] T004 [US3] In `src/infrahub_mcp/tools/schema.py` replace the `depth: int` param with `expand: bool | None` (defaulting to `config.schema_expand_peers`); call `get_schema_detail(..., expand_peers=...)`; drop negative-depth handling. In `src/infrahub_mcp/resources/schema.py` use `config.schema_expand_peers` and update the resource description. Grep-verify no `max_query_depth`/`depth=` remain in `src/`. Lint + type-check. Commit.

**Checkpoint**: US3 fully functional; live `test_tools.py` schema cases remain valid (CI).

---

## Phase 4: User Story 1 + 2 core - Traversal logic (Priority: P1/P2)

**Goal**: resolution, shaping, orchestration for both traversal tools.
**Independent Test**: `tests/unit/test_traversal.py` mock-client tests for resolution (UUID/HFID/malformed/not-found), shaping, orchestration, and version propagation.

- [ ] T005 [US1] [US2] Create `src/infrahub_mcp/traversal.py`: `NodeResolutionError`, `resolve_node_ref`, `_shape_node`/`_shape_hop`/`_shape_path`, `shape_path_result`, `shape_reachable_result`, `run_find_paths`, `run_find_reachable` (default `max_results=20`). Create `tests/unit/test_traversal.py` core tests. TDD. Lint. Commit.

**Checkpoint**: Traversal core verified offline.

---

## Phase 5: User Story 1 + 2 tools - MCP wrappers + wiring (Priority: P1/P2) 🎯 MVP

**Goal**: expose `find_paths` / `find_reachable`; mount in server.
**Independent Test**: mock-ctx tests for `_find_paths_impl`/`_find_reachable_impl` (happy → TOON; version error → ToolError; resolution error → ToolError); server registers both tools.

- [ ] T006 [US1] [US2] Create `src/infrahub_mcp/tools/traversal.py`: `_find_paths_impl`/`_find_reachable_impl` (catch `VersionNotSupportedError`/`NodeResolutionError` → `_log_and_raise_error`) and the two `@mcp.tool(readOnlyHint=True, tags={"traversal","retrieve"})` wrappers. Mount `traversal_mcp` in `src/infrahub_mcp/server.py` and add tool descriptions + the "prefer traversal over hand-built deep queries" nudge. Append tool-wrapper tests to `tests/unit/test_traversal.py`. TDD. Lint + type-check. Commit.

**Checkpoint**: MVP — both traversal tools callable and registered.

---

## Phase 6: Polish & Docs

- [ ] T007 [P] Add `find_paths`/`find_reachable` sections to `docs/docs/references/methods.mdx` and the `expand` param to `get_schema`; add any Vale terms. Run `uv run rumdl check docs/docs/`, full `uv run pre-commit run --all-files`, the offline unit tests, and (CI/live only) the full suite + docs build. Commit.

---

## Dependencies & Execution Order

- **T001** (setup) → blocks everything (SDK must import).
- **T002, T003** (foundational, [P]) → after T001; independent of each other.
- **T004** (US3) → after T002 + T003 (consumes new config + new `get_schema_detail`).
- **T005** (traversal core) → after T001 (uses SDK models); independent of T002–T004.
- **T006** (traversal tools) → after T005.
- **T007** (docs/polish) → after T004 + T006.

### Parallel opportunities

- T002 ∥ T003 (different files).
- T005 can proceed in parallel with T002–T004 (different files; only shares the T001 SDK floor).

## Implementation Strategy

MVP = T001 → T005 → T006 (the two traversal tools, the feature's headline value). Schema slim (T002–T004) and docs (T007) complete the change. Commit after each task; verify tests fail before implementing (TDD); keep both new tools read-only.
