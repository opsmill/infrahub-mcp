---
description: "Task list for Infrahub Marketplace integration"
---

# Tasks: Infrahub Marketplace integration for the MCP server

**Input**: Design documents from `specs/002-marketplace-integration/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/mcp-tools.md

**Tests**: Included — the spec's "Testing Decisions" and Constitution V (Test Discipline) require unit, contract, and E2E coverage.

**Organization**: Tasks grouped by user story (US1 discover/read, US2 install, US3 collections) for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- File paths are exact.

## Path Conventions

Single project: `src/infrahub_mcp/`, `tests/` at repository root (per plan.md Structure Decision).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the new module skeletons the feature lives in.

- [x] T001 [P] Create `src/infrahub_mcp/marketplace.py` skeleton (module docstring, imports, `from __future__ import annotations`)
- [x] T002 [P] Create `src/infrahub_mcp/tools/marketplace.py` skeleton with two FastMCP instances: `mcp = FastMCP(name="Infrahub Marketplace")` (reads) and `install_mcp = FastMCP(name="Infrahub Marketplace Install")` (write)
- [x] T003 [P] Create empty test files `tests/unit/test_marketplace_client.py`, `tests/unit/test_marketplace_tools.py`, `tests/integration/test_marketplace_install.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Config, client core, error handling, and mounting that ALL user stories depend on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [x] T004 Extend `ServerConfig` in `src/infrahub_mcp/config.py` with `marketplace_enabled: bool = True` and `marketplace_url: str = "https://marketplace.infrahub.app"`; add a field validator that enforces a well-formed http(s) URL and strips the trailing slash (FR-007, FR-008)
- [x] T005 [P] In `src/infrahub_mcp/marketplace.py`: define `MarketplaceIdentifier` (parse `namespace/name`, reject malformed → `invalid-ref`), the `MarketplaceError` category enum (`invalid-ref`, `not-found`, `no-such-version`, `unreachable`, `too-large`), and the typed result models (`CatalogEntry`, `SchemaPayload`, `CollectionPayload`, `InstallResult`) per data-model.md
- [x] T006 [P] In `src/infrahub_mcp/marketplace.py`: implement `_make_http_client(sdk_cfg)` that builds an `httpx.AsyncClient` carrying NO Infrahub credentials, inheriting SDK proxy/`proxy_mounts`/`verify=tls_context`, `follow_redirects=True` (FR-009) — mirror `infrahub_sdk.ctl.marketplace._make_http_client`
- [x] T007 In `src/infrahub_mcp/marketplace.py`: implement the download URL builders (`_schema_url`, `_collection_url`) and `_detect_item_type` parallel probe with schema-wins-on-tie + ambiguity note (FR-011), mapping transport/5xx → `unreachable`, both-404 → `not-found` (depends on T005, T006). *(Note: `_collection_url` == the collection `_detail_url` from T011 — implement once and share, don't duplicate.)*
- [x] T008 Wire gated mounting in `src/infrahub_mcp/server.py`: import `mcp as marketplace_mcp` and `install_mcp as marketplace_install_mcp`; add `if _config.marketplace_enabled: mcp.mount(marketplace_mcp)` and nested `if not _config.read_only: mcp.mount(marketplace_install_mcp)` after the existing write-mount block
- [x] T009 [P] Unit test in `tests/unit/test_marketplace_tools.py`: config gating — `marketplace_enabled=False` registers no marketplace tools and makes no HTTP call; malformed `marketplace_url` fails at startup (SC-003, FR-007)
- [x] T010 [P] Unit test in `tests/unit/test_marketplace_client.py`: `MarketplaceIdentifier` parsing (valid + malformed→invalid-ref), error-category mapping, and auto-detect (schema-wins, unreachable vs not-found) against mocked httpx

**Checkpoint**: Config, client core, error mapping, and mounting ready — user stories can begin.

---

## Phase 3: User Story 1 — Discover and read a marketplace schema (Priority: P1) 🎯 MVP

**Goal**: Agent can search the catalog and fetch a schema's metadata + decompressed YAML (latest or pinned version) without a browser.

**Independent Test**: With a mocked marketplace serving a "dcim" match and `opsmill/dcim` download, `marketplace_search("dcim")` returns ranked entries and `marketplace_get_schema("opsmill/dcim")` returns metadata + YAML.

- [x] T011 [US1] Port the list/search/detail endpoint contract from SDK PR #1128 into `src/infrahub_mcp/marketplace.py`: `_list_url` (`/api/v1/{schemas|collections}`), `_detail_url` (`.../{ns}/{name}`), and a `_fetch_listing` cursor-pagination helper (`search`/`limit`/`cursor` params, stop on `has_next_page` false or missing cursor) — contract confirmed in research.md Decision 3, no live probe needed
- [x] T012 [P] [US1] Implement `search(query, tag, namespace, limit) -> list[CatalogEntry]` in `src/infrahub_mcp/marketplace.py` on top of `_fetch_listing` (empty list on no match, `unreachable` on transport/5xx/invalid-JSON). `tag`/`namespace` filter client-side on the returned `namespace`/`tags` fields unless a server-side param is confirmed (research.md Decision 3 residual) (FR-001)
- [x] T013 [P] [US1] Implement `get_schema(ref, version) -> SchemaPayload` in `src/infrahub_mcp/marketplace.py`: resolve/auto-detect, **fetch catalog metadata via `_detail_url`** (T011) AND download the YAML (latest or pinned) via `_schema_url`, read `x-schema-version`, decompress if needed, map `no-such-version` (versioned 404 when schema exists) vs `not-found`. Populate both `SchemaPayload.metadata` and `.yaml` — FR-002 requires metadata *and* YAML (FR-002, FR-010, FR-011) (depends on T007, T011)
- [x] T014 [US1] Add the `marketplace_search` tool in `src/infrahub_mcp/tools/marketplace.py` (`mcp`, tags `{"marketplace","retrieve"}`, `readOnlyHint=True`, returns compact JSON), delegating to the client and raising via `_log_and_raise_error` (FR-001, FR-004)
- [x] T015 [US1] Add the `marketplace_get_schema` tool in `src/infrahub_mcp/tools/marketplace.py` (`mcp`, `readOnlyHint=True`, returns YAML/metadata), delegating to `get_schema` (FR-002, FR-004, FR-010, FR-011)
- [x] T016 [P] [US1] Unit tests in `tests/unit/test_marketplace_client.py` for `search` (pagination, filters, empty, unreachable) and `get_schema` (latest, pinned, no-such-version, gzip payload, metadata populated) against mocked httpx; **assert outbound marketplace requests carry no Infrahub auth header** (FR-009, Constitution VI)
- [x] T017 [P] [US1] Tool tests in `tests/unit/test_marketplace_tools.py`: `marketplace_search` / `marketplace_get_schema` output shape and error surfacing (readOnlyHint present; sanitised errors)

**Checkpoint**: US1 fully functional — discovery + read works end to end (MVP).

---

## Phase 4: User Story 2 — Install a marketplace schema (Priority: P2)

**Goal**: Agent installs a chosen schema into the connected Infrahub on a session branch for review; default branch untouched; blocked in read-only.

**Independent Test**: With marketplace enabled and not read-only, `marketplace_install("opsmill/dcim")` loads onto the session branch and reports it; default branch unchanged. In read-only mode the call is blocked before any HTTP.

- [x] T018 [US2] Implement `marketplace_install` in `src/infrahub_mcp/tools/marketplace.py` (`install_mcp`, tags `{"marketplace","write"}`): resolve ref → `get_schema` download → parse YAML to `list[dict]` → `get_or_create_session_branch(ctx)` → `client.schema.load(schemas=..., branch=session_branch)` → return `InstallResult` with branch + applied summary. *(FR-012 audit is satisfied automatically: `AuditMiddleware.on_call_tool` logs every tool call — no extra code needed, just don't bypass the tool layer.)* (FR-005, FR-012)
- [x] T019 [US2] Ensure read-only enforcement: verify `install_mcp` is only mounted when not read-only (T008) AND the `"write"` tag causes `ReadOnlyMiddleware` to block it; confirm no marketplace HTTP is issued when blocked (FR-006)
- [x] T020 [US2] Map install-path errors in `src/infrahub_mcp/tools/marketplace.py`: SDK schema-validation failure surfaces the SDK error on the branch (default branch untouched); ref/network errors via the shared categories (FR-010)
- [x] T021 [P] [US2] Tool tests in `tests/unit/test_marketplace_tools.py`: read-only guard blocks before HTTP; session-branch routing (uses `get_or_create_session_branch`); validation-failure leaves default branch untouched (mock `client.schema.load`)
- [x] T022 [US2] E2E test in `tests/integration/test_marketplace_install.py`: search → get_schema → install onto a session branch against a testcontainers Infrahub (builds on `001-infrahub-testcontainers`), asserting the default branch is untouched (SC-002)

**Checkpoint**: US1 + US2 both work independently — discover, read, and install with review gate.

---

## Phase 5: User Story 3 — Adopt a Collection bundle (Priority: P3)

**Goal**: Agent fetches a collection's ordered member schemas as a valid multi-document YAML stream.

**Independent Test**: `marketplace_get_collection("opsmill/starter")` returns metadata + members assembled as `---`-separated multi-doc YAML.

- [x] T023 [US3] Implement `get_collection(ref) -> CollectionPayload` in `src/infrahub_mcp/marketplace.py`: fetch collection metadata, download each member schema, assemble a valid multi-document YAML stream (`---` separators), map `too-large` (413) and `not-found`/`unreachable` (FR-003, FR-010) (depends on T007, T013)
- [x] T024 [US3] Add the `marketplace_get_collection` tool in `src/infrahub_mcp/tools/marketplace.py` (`mcp`, `readOnlyHint=True`), delegating to `get_collection` (FR-003, FR-004)
- [x] T025 [P] [US3] Unit tests in `tests/unit/test_marketplace_client.py`: `get_collection` member assembly (valid multi-doc YAML), `too-large` 413 mapping, not-found

**Checkpoint**: All three user stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T026 [P] Add user-facing docs for marketplace tools + config in `docs/docs/` (`.mdx`, Diataxis); run `uv run rumdl check docs/docs/`
- [x] T027 [P] Update `src/infrahub_mcp/server.py` `infrahub_agent` prompt to mention marketplace tools when enabled (mirror the read/write tool listing)
- [x] T028 [P] Record the external-service-call decision in `dev/adr/` (marketplace client bypasses SDK for its own API but loads into Infrahub via the SDK — Constitution II boundary), and add the new `marketplace` tool module + external-call flow to `dev/knowledge/architecture.md` (Constitution "Architecture changes MUST update dev/knowledge/")
- [x] T029 Run `uv sync && uv run invoke format lint && uv run pytest` — zero errors; then `quickstart.md` validation (enable/disable, read-only block, install branch isolation)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: after Setup — BLOCKS all user stories. T007 depends on T005/T006; T008 depends on T004.
- **User Stories (Phase 3–5)**: after Foundational. Priority order P1 → P2 → P3; independently testable.
- **Polish (Phase 6)**: after desired stories complete.

### User Story Dependencies

- **US1 (P1)**: needs Foundational only. T011 (port endpoint contract from #1128) blocks T012 (`_fetch_listing`) and T013 (`_detail_url` metadata).
- **US2 (P2)**: reuses `get_schema` (T013) for download; otherwise independent. Session-branch + read-only conventions from Foundational (T008).
- **US3 (P3)**: reuses `get_schema` download (T013) for members; otherwise independent.

### Parallel Opportunities

- Setup: T001, T002, T003 all [P].
- Foundational: T005, T006 [P]; T009, T010 [P] once their targets exist.
- US1: T012, T013 [P] (different functions, but both in `marketplace.py` — coordinate edits); T016, T017 [P].
- US3: T025 [P].
- Polish: T026, T027, T028 [P].

---

## Parallel Example: User Story 1

```bash
# After Foundational + T011 (endpoint helpers ported from #1128):
Task: "Implement search() in src/infrahub_mcp/marketplace.py"        # T012
Task: "Implement get_schema() in src/infrahub_mcp/marketplace.py"    # T013
# Then tests together:
Task: "Client unit tests in tests/unit/test_marketplace_client.py"   # T016
Task: "Tool tests in tests/unit/test_marketplace_tools.py"           # T017
```

---

## Implementation Strategy

### MVP First (User Story 1 only)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1 → **STOP & validate** discovery/read works → demo.

### Incremental Delivery

Foundation → US1 (MVP: discover/read) → US2 (install w/ review gate) → US3 (collections). Each story adds value without breaking the previous.

---

## Notes

- **Blocking unknown**: T011 must resolve the search endpoint before US1's search half (research.md Decision 3). US2/US3 use confirmed endpoints and are unblocked if search slips.
- `marketplace.py` is a single file touched by several [P] tasks — parallel only if edits are coordinated (distinct functions).
- Commit after each task or logical group; run `uv run invoke format lint` before commits (Constitution quality gates).
- Governance: API + authorization change → maintainer sign-off before merge (AGENTS.md "Ask First").

## Implementation status

All 29 tasks implemented; `uv run invoke format lint` clean (ruff, mypy, pylint 10.00/10) and `uv run pytest` green (339 passed, 37 new marketplace unit tests). Two items depend on live resources: **T011 has been verified live**, **T022 is Docker-gated and mock-only so far**:

- **T011** — ✅ **verified live** against `marketplace.infrahub.app` (2026-07-03): search, get_schema (latest + pinned + no-such-version), get_collection (5-member fan-out), and not-found all work. The live probe caught a field-name mismatch vs PR #1128's fixtures (`tags` are `{id,name}` dicts, `display_name`/`download_count`/`author.username`); `_catalog_entry` fixed and unit-tested against the real shape.
- **T022** — E2E install test written but Docker-gated (`-m integration`, deselected by default), consistent with the existing `001-infrahub-testcontainers` harness state. Run `uv run pytest -m integration` with Docker to verify end-to-end.
