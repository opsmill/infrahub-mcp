---
description: "Task list for schema-discovery guidance in every MCP client"
---

# Tasks: Schema-Discovery Guidance in Every MCP Client

**Input**: Design documents from `specs/004-schema-discovery-guidance/`
**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/server-instructions.md](./contracts/server-instructions.md), [contracts/mcp-surface.md](./contracts/mcp-surface.md), [quickstart.md](./quickstart.md)

**Tests**: Included. The spec checks SC-002 to SC-006 with unit tests, and constitution principle V requires tests with every change. Within each phase, write the tests first and confirm they fail before the implementation task.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel with other [P] tasks of the same phase (different files, no dependency on an unfinished task)
- **[Story]**: US1 = answer a question without guessing the schema; US2 = use the schema already in context; US3 = read the schema of a session branch

## Path Conventions

Single project: `src/infrahub_mcp/`, `tests/unit/`, `docs/docs/`, `dev/` at the repository root. Line numbers refer to `stable` at `36b80f9`.

---

## Phase 1: Setup

**Purpose**: Confirm the starting point and the prerequisite fix.

- [ ] T001 (pending: fix not merged on 2026-10-12) Check that the `get_nodes` paging fix (spec Assumptions; separate issue, not yet filed) has merged into `stable`. If it has, merge `stable` into `feat/schema-discovery-guidance` and run `uv sync`. If it has not, continue with the other tasks; T034 (manual SC-001 check) and the merge of this feature wait for it.
- [X] T002 Run `uv run invoke format lint` and `uv run pytest` on `feat/schema-discovery-guidance` and record that both pass before any change.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The guidance text and the setting it depends on. Every user story phase uses `build_instructions`.

- [X] T003 [P] Write `tests/unit/test_instructions.py` for `build_instructions(*, read_only, resources_as_tools)`, following the "Tests" list in [contracts/server-instructions.md](./contracts/server-instructions.md):
  - all four variants contain `get_schema()`, `get_schema(kind=`, `Never guess`, `get_nodes`, `total_count`, `find_paths`, `find_reachable` and `there is no "filters" argument`;
  - all four variants contain the "do not fetch it again" rule (FR-008);
  - variants 1 and 2 (read and write) contain `get_session_info` and `propose_changes`; variants 3 and 4 (read-only) contain none of the names of the tools registered in `src/infrahub_mcp/tools/write.py`, read from the `write_mcp` server rather than a hard-coded list;
  - variants 2 and 4 contain `infrahub://branches` and `infrahub://graphql-schema`; variants 1 and 3 contain neither `read_resource` nor `list_resources`;
  - every variant is under 2,000 characters.
- [X] T004 [P] Add `resources_as_tools: bool = False` to `ServerConfig` in `src/infrahub_mcp/config.py`, with an entry in the class docstring's attribute list. Add tests to `tests/unit/test_config.py`: the default is `False`, and `INFRAHUB_MCP_RESOURCES_AS_TOOLS=true` sets it to `True`.
- [X] T005 Create `src/infrahub_mcp/instructions.py` with `build_instructions(*, read_only: bool, resources_as_tools: bool) -> str`, using the target text in [contracts/server-instructions.md](./contracts/server-instructions.md). Depends on T003 (tests fail first). T003 passes.
- [X] T006 Regenerate the files that CI checks against `ServerConfig`: run `uv run invoke gen-config-env --update` (updates `docker-compose.yml`) and `uv run invoke validate-serverjson --update` (updates `server.json`). Depends on T004.

**Checkpoint**: `build_instructions` returns the four variants, and the setting exists. Nothing is sent to clients yet.

---

## Phase 3: User Story 1 - Answer a question without guessing the schema (Priority: P1)

**Goal**: A client that passes only tools, with no prompt selected, receives the schema-first rule, the tool-choice rules and the GraphQL filter rule in tool descriptions, parameter descriptions and error messages. Clients that pass server instructions also receive the full guidance text.

**Independent Test**: The automated tests below, then the manual check in [quickstart.md](./quickstart.md) section 3 (T034).

### Tests for User Story 1

- [X] T007 [P] [US1] Write `tests/unit/test_server_instructions.py`. For each of the four variants, start the server in a fresh interpreter (the pattern of `tests/unit/test_read_only_prompts.py` from PR 193: `subprocess.run([sys.executable, "-c", ...])` with `INFRAHUB_MCP_READ_ONLY` and `INFRAHUB_MCP_RESOURCES_AS_TOOLS` set) and check that `Client.instructions` equals `build_instructions(...)` for those settings.
- [X] T008 [P] [US1] Write `tests/unit/test_tool_descriptions.py`. List every tool (with its parameter descriptions) and every prompt through the in-memory FastMCP `Client`, in read-and-write mode, and check:
  - SC-002: no description names an `infrahub://` URI unless it also names a tool;
  - FR-004: the descriptions of `get_nodes`, `search_nodes`, `query_graphql`, `node_upsert` and their `kind` and `filters` parameters name `get_schema`, and do not contain "does not support MCP resources";
  - FR-006: the `get_schema` description does not contain "Prefer reading";
  - FR-007: the `query_graphql` description contains a filter example of the form `<Kind>(<key>: ...)` and the words `no "filters" argument`;
  - FR-017: the `get_schema` description and the `get_nodes` `filters` parameter description say the keys are GraphQL arguments of the kind's query.
- [X] T009 [P] [US1] Add tests to `tests/unit/test_gql_remediation.py` for the `query_graphql` remediation (FR-016, SC-006). (`tests/unit/test_tools.py` runs only against a live Infrahub instance, so these offline tests get their own file.)
  - a mocked `GraphQLError` whose `errors` contains `Unknown argument 'filters' on field 'Query.LocationSite'`, for the query `{ LocationSite(filters: {name__value: "x"}) { count } }`, returns a remediation containing `LocationSite(name__value:`;
  - a query with no top-level field name falls back to `DcimDevice`;
  - any other `GraphQLError` returns the existing remediation.
- [X] T010 [P] [US1] Update `tests/unit/test_server_prompt.py`: the `infrahub_agent` prompt contains `build_instructions(...)` for the server's settings, and no longer contains its own "Data formats" or "Schema discovery" sections.
- [X] T011 [P] [US1] Update `tests/unit/test_middleware.py` (`TestReadOnlyMiddleware`; `tests/unit/test_read_only.py` covers mutation detection only): `ReadOnlyMiddleware._KNOWN_READ_ONLY_TOOLS` contains `list_resources`, `read_resource`, `find_paths`, `find_reachable` and `get_session_info` (research R8, FR-014).

### Implementation for User Story 1

- [X] T012 [US1] In `src/infrahub_mcp/server.py`, pass `instructions=build_instructions(read_only=_config.read_only, resources_as_tools=_config.resources_as_tools)` to `FastMCP(...)` (line 102). Rebuild `infrahub_agent` (line 194) as: the persona line, then `build_instructions(...)`, then the tool overview; remove its "Data formats" and "Schema discovery" sections. T007 and T010 pass.
- [X] T013 [P] [US1] In `src/infrahub_mcp/tools/schema.py`, rewrite the `get_schema` description (lines 43-61): it is the step to take first; it may mention the `infrahub://schema` resource for hosts that attach it, without telling the assistant to prefer it (FR-006); the listed filter keys are also GraphQL arguments of the kind's query, not a `filters` argument (FR-017). Do not change the arguments or the output (FR-011).
- [X] T014 [P] [US1] In `src/infrahub_mcp/tools/nodes.py`, name `get_schema` / `get_schema(kind=...)` instead of resource URIs in: the `kind` parameter descriptions (lines 141, 309), the `filters` parameter description (line 154, also stating that in `query_graphql` the same keys go directly on the kind's query, FR-017), the `get_nodes` description (lines 195-204), the `search_nodes` description (lines 336-337) and the error remediations (lines 113, 263) (FR-004, FR-005).
- [X] T015 [P] [US1] In `src/infrahub_mcp/tools/gql.py`:
  - rewrite the description (lines 40-42) to name `get_schema` and state the filter syntax with one example (FR-004, FR-007);
  - in the `GraphQLError` handler (line 65), when a message in `exc.errors` contains `Unknown argument 'filters'`, return the remediation from [contracts/mcp-surface.md](./contracts/mcp-surface.md), using the first top-level field of the already parsed `document` as the kind name, or `DcimDevice` when there is none (FR-016).
  T009 passes.
- [X] T016 [P] [US1] In `src/infrahub_mcp/tools/write.py`, name `get_schema` instead of resource URIs in the `node_upsert` and `mutate_graphql` descriptions, parameters and errors (lines 113, 138, 144, 169-171, 244), and the same references in `node_delete` and `mutate_graphql` (lines 255, 266, 280, 331, 441-443, 465) (FR-004, FR-005).
- [X] T017 [P] [US1] In `src/infrahub_mcp/middleware.py`: change the response-size remediation (line 587) to name `get_schema(kind=...)`; add the five names from T011 to `_KNOWN_READ_ONLY_TOOLS` (line 157). T011 passes.
- [X] T018 [P] [US1] In `src/infrahub_mcp/prompts/prompts.py`, name `get_schema` / `get_schema(kind=...)` first and the resource second (lines 41, 58, 103, 113, 155, 168, 170).
- [X] T019 [US1] Run `uv run invoke format lint` and `uv run pytest`. T007 to T011 pass. Depends on T012 to T018.

**Checkpoint**: User Story 1 is complete for the automated checks. It can be shipped on its own; the manual SC-001 check (T034) is in the final phase because it needs the paging fix (T001).

---

## Phase 4: User Story 2 - Use the schema already in context (Priority: P2)

**Goal**: An assistant that already has the schema in the conversation does not fetch it again.

**Independent Test**: In a client that supports resources, attach `infrahub://schema` and ask a question about a kind in the catalog; the assistant does not read the catalog again.

- [ ] T020 [US2] (automated part done in T003; manual check pending) Confirm that T003 covers FR-008 in all four variants. Run the independent test above by hand in a client that supports resources (for example Claude Code or Claude Desktop) and record the result in the pull request.

**Checkpoint**: The implementation is in Phase 2 (FR-008 is one line of the guidance text). This phase is a check only.

---

## Phase 5: User Story 3 - Read the schema of a session branch (Priority: P3)

**Goal**: The schema resources accept a branch and return the same data as `get_schema` for the same kind and branch.

**Independent Test**: Read `infrahub://schema/<Kind>?branch=<branch>` and call `get_schema(kind="<Kind>", branch="<branch>")`; both return the same text ([quickstart.md](./quickstart.md) section 4).

### Tests for User Story 3

- [X] T021 [P] [US3] Write `tests/unit/test_schema_resources_branch.py`, with the SDK client mocked:
  - `infrahub://schema` is still listed by `list_resources` (static resource) and reads the default branch;
  - `infrahub://schema?branch=b1` and `infrahub://schema/LocationSite?branch=b1` call the helpers with `branch="b1"`;
  - `infrahub://schema/LocationSite` calls them with `branch=None`;
  - for the same kind and branch, the resource text equals the `get_schema` output (SC-004);
  - an unknown branch raises `ResourceError` with a message that names `get_schema()`.

### Implementation for User Story 3

- [X] T022 [US3] In `src/infrahub_mcp/resources/schema.py`:
  - add the template `infrahub://schema{?branch}` next to the static `infrahub://schema`;
  - change the kind template to `infrahub://schema/{kind}{?branch}`;
  - pass `branch` to `get_schema_catalog` / `get_schema_detail`;
  - handle `BranchNotFoundError` in the kind resource with a message that names `get_schema()` (FR-010).

  T021 passes.

**Checkpoint**: User Story 3 works on its own; it does not depend on Phase 3.

---

## Phase 6: Resource tools for clients that pass only tools (FR-012, FR-014, FR-015, SC-005)

**Goal**: With `INFRAHUB_MCP_RESOURCES_AS_TOOLS=true`, a client that passes only tools can read the branch list and the GraphQL schema through `read_resource`. This extends User Story 1 for operators behind a tools-only gateway.

**Independent Test**: With the setting on, `read_resource(uri="infrahub://branches")` returns the branch list in one tool call.

### Tests for the resource tools setting

- [X] T023 [P] [US1] Write `tests/unit/test_resources_as_tools.py`, one fresh interpreter per case:
  - setting off: `list_resources` and `read_resource` are not in the tool list, and the instructions do not mention them;
  - setting on: both tools are listed, `read_resource(uri="infrahub://branches")` returns the branch list (mocked `client.branch.all`), and the instructions name both URIs;
  - setting on with read-only: both tools are listed and callable;
  - setting on with token passthrough and no credential: `read_resource` is rejected, as a direct resource read is;
  - setting on: the resource read through `read_resource` is written to the audit log.

### Implementation for the resource tools setting

- [X] T024 [US1] In `src/infrahub_mcp/server.py`, after all `mcp.mount(...)` calls (after line 288), add `if _config.resources_as_tools: mcp.add_transform(ResourcesAsTools(mcp))`. T023 passes. Depends on T012 (same file).
- [ ] T025 [US1] (pending: no Docker daemon in the implementation session on 2026-10-12) Measure the size of `infrahub://graphql-schema` on the integration test instance (`tests/integration/`). Record the size in [research.md](./research.md) R3. If it is over 500 KB, add the limit to the documentation in T027.

**Checkpoint**: The setting works on its own and changes nothing when it is off.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [ ] T026 [P] Add `INFRAHUB_MCP_RESOURCES_AS_TOOLS` to the variable table in `docs/docs/references/configuration.mdx`.
- [ ] T027 [P] Update `docs/docs/references/methods.mdx` (server instructions, the optional `branch` on schema resources, the two optional resource tools, the `query_graphql` remediation for a `filters` argument) and `docs/docs/readme.mdx` line 28 (server instructions next to the `infrahub_agent` prompt). Include the GraphQL schema size limit if T025 found it. Run `uv run rumdl check docs/docs/`.
- [ ] T028 [P] Write `dev/adr/0009-guidance-in-instructions-and-descriptions.md` from `.specify/templates/adr-template.md`: model guidance lives in server instructions and tool descriptions; prompts carry workflows; resources serve hosts; `get_schema` is kept (research R1, R2).
- [ ] T029 [P] Add one paragraph to `dev/knowledge/architecture.md` on where model guidance lives.
- [ ] T030 [P] Create the changelog fragment with `uv run towncrier create -c "<text>" 191.added.md`.
- [ ] T031 Regenerate `CAPABILITIES.md` with `uv run invoke update-capabilities` (needs the `mcp-discovery` CLI; see `scripts/update-capabilities.sh`). CI (`ci-mcp-discovery.yml`) fails if it is out of date. Depends on all description changes (T013 to T018, T022, T024).
- [ ] T032 Run the full gate: `uv sync && uv run pre-commit run && uv run pytest && uv run invoke lint && uv run invoke validate-dockercomposeenv && uv run invoke validate-serverjson && uv run rumdl check docs/docs/`.
- [ ] T033 Run [quickstart.md](./quickstart.md) section 2 (what a client receives) for the four variants.
- [ ] T034 Run the manual SC-001 check in [quickstart.md](./quickstart.md) section 3: 3 runs with Claude through a client that passes only tools; at least 2 must pass; record all three in the pull request. Depends on T001 (paging fix merged).
- [ ] T035 Open the pull request against `stable` with the label `changes/minor`, linking issue 191 and the `get_nodes` paging issue. Merge waits on T034.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies. T001 gates only T034 and the merge.
- **Foundational (Phase 2)**: depends on Setup. Blocks Phases 3, 4 and 6.
- **User Story 1 (Phase 3)**: depends on Phase 2.
- **User Story 2 (Phase 4)**: depends on Phase 2 (the text) and is checked after Phase 3 (the text is sent).
- **User Story 3 (Phase 5)**: depends only on Setup. Can run in parallel with Phases 2 to 4.
- **Resource tools (Phase 6)**: depends on Phase 2 (T004, T005) and on T012 (same file as T024).
- **Polish (Phase 7)**: T026 to T030 can start once the behavior they describe is done. T031 depends on all description changes. T034 depends on T001.

### Within Each Phase

- Tests first, and they must fail before the implementation task.
- Tasks that edit the same file run in order: `server.py` (T012, then T024).

### Parallel Opportunities

- Phase 2: T003 and T004.
- Phase 3: tests T007 to T011 together; then implementation T013 to T018 together (six files), with T012 alongside them since it edits `server.py` only.
- Phase 5 can run alongside Phase 3 (different files).
- Phase 7: T026 to T030 together.

## Parallel Example: User Story 1

```text
# Tests, all at once (different files):
T007 tests/unit/test_server_instructions.py
T008 tests/unit/test_tool_descriptions.py
T009 tests/unit/test_tools.py
T010 tests/unit/test_server_prompt.py
T011 tests/unit/test_read_only.py

# Implementation, all at once (different files):
T012 src/infrahub_mcp/server.py
T013 src/infrahub_mcp/tools/schema.py
T014 src/infrahub_mcp/tools/nodes.py
T015 src/infrahub_mcp/tools/gql.py
T016 src/infrahub_mcp/tools/write.py
T017 src/infrahub_mcp/middleware.py
T018 src/infrahub_mcp/prompts/prompts.py
```

## Implementation Strategy

### First increment: User Story 1

1. Phase 1 and Phase 2.
2. Phase 3 (User Story 1).
3. Stop and check: run T019 and quickstart section 2 (T033). This increment fixes the issue 191 behavior for every client that passes only tools.

### Next increments

1. Phase 4 (User Story 2): a manual check only.
2. Phase 5 (User Story 3): branch-aware resources.
3. Phase 6: the resource tools setting.
4. Phase 7: documentation, regenerated files, the manual SC-001 check and the pull request.

All increments go into one pull request (`changes/minor`), because the manual SC-001 check (T034) gates the merge of the whole feature.
