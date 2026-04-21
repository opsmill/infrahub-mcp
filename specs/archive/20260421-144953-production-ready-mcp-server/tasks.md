# Tasks: Production-Ready MCP Server (INFP-411)

**Input**: Design documents from `specs/20260421-144953-production-ready-mcp-server/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md

**Note**: Retrospective task list — all tasks described here are already implemented.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Configuration model and core server structure

- [ ] T001 Define `ServerConfig` frozen Pydantic model with `INFRAHUB_MCP_*` env prefix in `src/infrahub_mcp/config.py`
- [ ] T002 Define `AuthMode` literal type (`none`, `oidc`, `token-passthrough`, `basic-passthrough`) in `src/infrahub_mcp/config.py`
- [ ] T003 [P] Implement `load_config()` with OIDC field validation at boundary in `src/infrahub_mcp/config.py`
- [ ] T004 [P] Define `AppContext` dataclass for lifespan dependency injection in `src/infrahub_mcp/server.py`
- [ ] T005 [P] Add shared constants (allowlisted read-only tools) in `src/infrahub_mcp/constants.py`

**Checkpoint**: Config loads from env vars, validates at startup, and AppContext is available via lifespan

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Middleware composition framework and ContextVar infrastructure — MUST be complete before any user story

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T006 Implement `configure_middleware()` entry point that composes the middleware stack based on `ServerConfig` in `src/infrahub_mcp/middleware.py`
- [ ] T007 [P] Define ContextVars for per-request state (`current_request_id`, `_passthrough_token`, `_passthrough_basic`, `_session_branch`) in `src/infrahub_mcp/middleware.py`
- [ ] T008 [P] Implement `RequestIdMiddleware` — assigns correlation ID via ContextVar in `src/infrahub_mcp/middleware.py`
- [ ] T009 [P] Implement `ErrorHandlingMiddleware` — exception-to-MCP-error translation in `src/infrahub_mcp/middleware.py`
- [ ] T010 [P] Implement `InfrahubConnectionMiddleware` — SDK connection error handling in `src/infrahub_mcp/middleware.py`
- [ ] T011 Wire `configure_middleware()` into FastMCP server construction in `src/infrahub_mcp/server.py`

**Checkpoint**: Foundation ready — middleware stack composes at startup, request IDs propagate, errors translate to MCP codes

---

## Phase 3: User Story 1 — Middleware Observability Stack (Priority: P1) 🎯 MVP

**Goal**: Structured logging, request correlation, performance metrics, health checks, and operational middleware (rate limiting, retry, caching)

**Independent Test**: Start the server, send tool calls, verify structured JSON logs with request IDs, `/health` responses, `/metrics` output, and rate limiting behavior

### Implementation for User Story 1

- [ ] T012 [P] [US1] Implement `StructuredLoggingMiddleware` — JSON structured logs with request ID, tool name, duration, token estimates in `src/infrahub_mcp/middleware.py`
- [ ] T013 [P] [US1] Implement `DetailedTimingMiddleware` — per-operation timing breakdown in `src/infrahub_mcp/middleware.py`
- [ ] T014 [P] [US1] Implement `MetricsMiddleware` — Prometheus counters and histograms in `src/infrahub_mcp/middleware.py`
- [ ] T015 [P] [US1] Implement `OTelTracingMiddleware` — OpenTelemetry span creation in `src/infrahub_mcp/middleware.py`
- [ ] T016 [P] [US1] Implement `RetryMiddleware` — transient failure retry with configurable backoff in `src/infrahub_mcp/middleware.py`
- [ ] T017 [P] [US1] Implement `RateLimitingMiddleware` — token-bucket algorithm with `rate_limit_rps` and `rate_limit_burst` in `src/infrahub_mcp/middleware.py`
- [ ] T018 [P] [US1] Implement `ResponseCachingMiddleware` — TTL-based caching for schema/list operations in `src/infrahub_mcp/middleware.py`
- [ ] T019 [P] [US1] Implement `ResponseLimitingMiddleware` — response size control as innermost layer in `src/infrahub_mcp/middleware.py`
- [ ] T020 [P] [US1] Implement `DereferenceRefsMiddleware` — JSON Schema `$ref` resolution in `src/infrahub_mcp/middleware.py`
- [ ] T021 [P] [US1] Implement `PingMiddleware` — HTTP session keep-alive in `src/infrahub_mcp/middleware.py`
- [ ] T022 [US1] Wire health check endpoint into ASGI app in `src/infrahub_mcp/server.py`
- [ ] T023 [US1] Wire Prometheus `/metrics` endpoint (conditional on `prometheus_enabled`) in `src/infrahub_mcp/server.py`

**Checkpoint**: Server produces structured JSON logs, exposes `/health` and `/metrics`, rate limits requests, caches responses, retries transient failures

---

## Phase 4: User Story 2 — Pass-Through Authentication (Priority: P1)

**Goal**: Per-user authentication via API token, username/password, or OIDC — preserving Infrahub's permission model and audit trail

**Independent Test**: Configure `auth_mode=token-passthrough`, send requests with/without valid Infrahub API token, verify authenticated succeed and unauthenticated are rejected

### Implementation for User Story 2

- [ ] T024 [P] [US2] Implement `_CredentialsPassthroughASGI` — ASGI middleware extracting Bearer token or Basic auth from configurable HTTP header, storing in ContextVar in `src/infrahub_mcp/server.py`
- [ ] T025 [P] [US2] Implement `set_passthrough_token()` / `get_passthrough_token()` ContextVar helpers in `src/infrahub_mcp/middleware.py`
- [ ] T026 [P] [US2] Implement `set_passthrough_basic()` / `get_passthrough_basic()` ContextVar helpers in `src/infrahub_mcp/middleware.py`
- [ ] T027 [US2] Implement `TokenPassthroughMiddleware` — fail-closed credential presence enforcement in `src/infrahub_mcp/middleware.py`
- [ ] T028 [US2] Implement `AuthMiddleware` — OIDC scope enforcement for write operations in `src/infrahub_mcp/middleware.py`
- [ ] T029 [US2] Implement OIDC provider factory and identity helpers in `src/infrahub_mcp/auth.py`
- [ ] T030 [US2] Integrate `OIDCProxy` from fastmcp for OAuth 2.0 flow in `src/infrahub_mcp/server.py`
- [ ] T031 [US2] Wire ASGI credential extraction into HTTP transport setup in `src/infrahub_mcp/server.py`

**Checkpoint**: Token-passthrough rejects unauthenticated requests, OIDC flow works end-to-end, credentials stored in ContextVar (never logged)

---

## Phase 5: User Story 3 — Read-Only Mode (Priority: P2)

**Goal**: Tag-based write tool filtering with defense-in-depth — hide, reject, and fail-closed allowlist

**Independent Test**: Start server with `read_only=true`, list tools (write tools absent), attempt direct write tool call (rejected), verify fail-closed allowlist behavior

### Implementation for User Story 3

- [ ] T032 [US3] Implement `ReadOnlyMiddleware` with `on_list_tools()` — filter tools tagged `"write"` from listings in `src/infrahub_mcp/middleware.py`
- [ ] T033 [US3] Add `on_call_tool()` to `ReadOnlyMiddleware` — block execution of tagged write tools in `src/infrahub_mcp/middleware.py`
- [ ] T034 [US3] Add fail-closed allowlist fallback to `ReadOnlyMiddleware` — only known-safe tools if tag resolution fails in `src/infrahub_mcp/middleware.py`
- [ ] T035 [US3] Implement `AuditMiddleware` — structured audit log for write operations in `src/infrahub_mcp/middleware.py`
- [ ] T036 [US3] Conditionally skip write sub-app mounting when `read_only=true` in `src/infrahub_mcp/server.py`

**Checkpoint**: Read-only mode hides write tools, rejects direct calls, and falls back to allowlist on tag errors

---

## Phase 6: User Story 4 — Auto Branching with Naming Convention (Priority: P2)

**Goal**: Lazy session branch creation with configurable naming pattern, collision retry, and default branch protection

**Independent Test**: Configure branch pattern, execute a write tool, verify new branch created with expected name, verify default branch writes blocked

### Implementation for User Story 4

- [ ] T037 [P] [US4] Implement `expand_branch_pattern()` — replace `{date}`, `{hex}`, `{user}` placeholders in `src/infrahub_mcp/utils.py`
- [ ] T038 [P] [US4] Implement `sanitize_user_for_branch()` — 8-rule regex pipeline for git ref-format compliance in `src/infrahub_mcp/utils.py`
- [ ] T039 [US4] Implement `get_or_create_session_branch()` — lazy creation on first write with collision retry in `src/infrahub_mcp/utils.py`
- [ ] T040 [US4] Implement `assert_writable_branch()` — block writes targeting the instance's default branch in `src/infrahub_mcp/utils.py`
- [ ] T041 [US4] Wire session branch into write tools (call `get_or_create_session_branch()` before SDK mutations) in `src/infrahub_mcp/tools/write.py`
- [ ] T042 [US4] Implement `get_session_info` tool reporting active session branch and status in `src/infrahub_mcp/tools/session.py`

**Checkpoint**: Write operations create session branches lazily, collisions retry, default branch is protected

---

## Phase 7: Unit Test Gaps

**Purpose**: Fill identified gaps in existing unit test coverage (253 tests across 12 files)

- [ ] T043 [P] Add unit test for `get_or_create_session_branch()` lazy creation flow in `tests/unit/test_tools.py`
- [ ] T044 [P] Add unit test for `StrictResponseLimitingMiddleware` tool-level limit in `tests/unit/test_middleware.py`
- [ ] T045 Verify middleware stack ordering matches R1 decision (outermost→innermost) in `src/infrahub_mcp/middleware.py`
- [ ] T046 Run full quality gates (`uv sync && uv run pre-commit run && uv run pytest`)

---

## Phase 8: Integration Test Infrastructure (Future — Testcontainers)

**Purpose**: Scaffold integration test framework using testcontainers for real Infrahub + Keycloak instances

**Prerequisites**: `testcontainers` added as dev dependency, Docker available in CI

### Infrastructure Setup

- [ ] T047 Add `testcontainers` and `httpx` to dev dependencies in `pyproject.toml`
- [ ] T048 [P] Create `tests/integration/__init__.py`
- [ ] T049 Create `tests/integration/conftest.py` with testcontainers fixtures:
  - `infrahub_container` — Infrahub server container with API available
  - `keycloak_container` — Keycloak container with pre-configured realm, clients, and test users
  - `mcp_server` — MCP server process configured against the Infrahub container
  - `mcp_client` — HTTP client pre-configured with MCP server URL
- [ ] T050 Add `pytest.ini` marker `integration` and CI config to skip integration tests by default (`-m "not integration"`)

### US1 — Observability Integration Tests

- [ ] T051 [P] [US1] Test `/health` endpoint returns healthy when Infrahub is reachable in `tests/integration/test_health_e2e.py`
- [ ] T052 [P] [US1] Test `/health` endpoint returns unhealthy when Infrahub is unreachable in `tests/integration/test_health_e2e.py`
- [ ] T053 [P] [US1] Test `/metrics` endpoint returns Prometheus-format counters after tool calls in `tests/integration/test_health_e2e.py`
- [ ] T054 [US1] Test structured JSON log output contains request ID, tool name, and duration for a real `query_graphql` call in `tests/integration/test_health_e2e.py`

### US2 — Authentication Integration Tests

- [ ] T055 [P] [US2] Test `token-passthrough`: valid Infrahub API token → tool call succeeds under user identity in `tests/integration/test_auth_passthrough.py`
- [ ] T056 [P] [US2] Test `token-passthrough`: missing token → request rejected before any Infrahub API call in `tests/integration/test_auth_passthrough.py`
- [ ] T057 [P] [US2] Test `token-passthrough`: invalid/expired token → Infrahub SDK raises auth error, translated to MCP error in `tests/integration/test_auth_passthrough.py`
- [ ] T058 [P] [US2] Test `basic-passthrough`: valid username/password → tool call succeeds in `tests/integration/test_auth_passthrough.py`
- [ ] T059 [P] [US2] Test `basic-passthrough`: wrong password → rejected with clear error in `tests/integration/test_auth_passthrough.py`
- [ ] T060 [US2] Test OIDC full flow: Keycloak token exchange → JWT validated → tool call succeeds with scope enforcement in `tests/integration/test_oidc_flow.py`
- [ ] T061 [US2] Test OIDC: read-only scoped token → write tool call rejected with scope error in `tests/integration/test_oidc_flow.py`
- [ ] T062 [US2] Test OIDC: unprovisioned user (valid JWT, no Infrahub credentials) → credential resolution error in `tests/integration/test_oidc_flow.py`

### US3 — Read-Only Mode Integration Tests

- [ ] T063 [US3] Test `read_only=true`: `list_tools` response contains zero write tools against real server in `tests/integration/test_read_only_e2e.py`
- [ ] T064 [US3] Test `read_only=true`: direct `call_tool("node_upsert", ...)` rejected with read-only error in `tests/integration/test_read_only_e2e.py`
- [ ] T065 [US3] Test `read_only=false`: write tools visible and callable (creates real object on session branch) in `tests/integration/test_read_only_e2e.py`

### US4 — Branch Lifecycle Integration Tests

- [ ] T066 [US4] Test lazy branch creation: first write tool call creates branch in Infrahub, verify via SDK `branch.all()` in `tests/integration/test_branch_lifecycle.py`
- [ ] T067 [US4] Test branch reuse: second write in same session targets existing session branch (no new branch) in `tests/integration/test_branch_lifecycle.py`
- [ ] T068 [US4] Test default branch protection: write targeting `main` blocked with clear error in `tests/integration/test_branch_lifecycle.py`
- [ ] T069 [US4] Test `{user}` placeholder: OIDC-authenticated write creates branch with sanitized username in `tests/integration/test_branch_lifecycle.py`
- [ ] T070 [US4] Test `get_session_info` returns active branch name and status after a write in `tests/integration/test_branch_lifecycle.py`

### Cross-Cutting Integration Tests

- [ ] T071 Test full request lifecycle: auth → middleware stack → tool call → structured log + metrics + audit entry in `tests/integration/test_full_lifecycle.py`
- [ ] T072 Test concurrent requests: two authenticated users operating in parallel have isolated ContextVars (no credential leaking) in `tests/integration/test_full_lifecycle.py`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational (Phase 2)
- **User Story 2 (Phase 4)**: Depends on Foundational (Phase 2)
- **User Story 3 (Phase 5)**: Depends on Foundational (Phase 2); integrates with US2 (auth-aware filtering)
- **User Story 4 (Phase 6)**: Depends on Foundational (Phase 2); integrates with US2 (user identity for `{user}` placeholder)
- **Unit Test Gaps (Phase 7)**: Depends on all user stories being complete
- **Integration Tests (Phase 8)**: Depends on Phase 7; requires Docker in CI; can be implemented incrementally per user story

### User Story Dependencies

- **US1 (Observability)**: Independent — no dependencies on other stories
- **US2 (Authentication)**: Independent — no dependencies on other stories
- **US3 (Read-Only)**: Soft dependency on US2 (auth-aware filtering), but independently testable with `auth_mode=none`
- **US4 (Auto Branching)**: Soft dependency on US2 (user identity for `{user}` placeholder), but independently testable with `{date}` and `{hex}` patterns

### Within Each User Story

- Models/entities before services
- ContextVar helpers before middleware that uses them
- Middleware before server wiring
- Core implementation before integration

### Integration Test Dependencies

- **Infrastructure setup** (T047–T050): Must complete before any integration test
- **US1 integration tests** (T051–T054): Only need Infrahub container — can run first
- **US2 integration tests** (T055–T062): Need Infrahub + Keycloak containers
- **US3 integration tests** (T063–T065): Need Infrahub container + write tools available
- **US4 integration tests** (T066–T070): Need Infrahub + Keycloak (for `{user}` test)
- **Cross-cutting tests** (T071–T072): Need full stack (Infrahub + Keycloak + all features)

### Parallel Opportunities

- All Setup tasks marked [P] can run in parallel (T003, T004, T005)
- All Foundational tasks marked [P] can run in parallel (T007, T008, T009, T010)
- US1 middleware layers (T012–T021) are all [P] — different classes in the same file, no mutual dependencies
- US2 ContextVar helpers (T025, T026) can run in parallel with ASGI middleware (T024)
- US4 pattern expansion (T037) and sanitization (T038) are [P]
- Unit test gap tasks (T043, T044) are [P]
- Integration tests within each story (T051–T053, T055–T059) are [P]
- **US1 and US2 can run fully in parallel** (different concerns, different middleware layers)

---

## Parallel Example: User Story 1

```bash
# Launch all observability middleware layers together (all [P]):
Task: "Implement StructuredLoggingMiddleware in src/infrahub_mcp/middleware.py"
Task: "Implement DetailedTimingMiddleware in src/infrahub_mcp/middleware.py"
Task: "Implement MetricsMiddleware in src/infrahub_mcp/middleware.py"
Task: "Implement OTelTracingMiddleware in src/infrahub_mcp/middleware.py"
Task: "Implement RetryMiddleware in src/infrahub_mcp/middleware.py"
Task: "Implement RateLimitingMiddleware in src/infrahub_mcp/middleware.py"
Task: "Implement ResponseCachingMiddleware in src/infrahub_mcp/middleware.py"
Task: "Implement ResponseLimitingMiddleware in src/infrahub_mcp/middleware.py"

# Then wire into server (sequential, depends on middleware):
Task: "Wire health check endpoint in src/infrahub_mcp/server.py"
Task: "Wire Prometheus /metrics endpoint in src/infrahub_mcp/server.py"
```

---

## Test Coverage Summary

### Unit Tests (253 tests — all passing)

| Story | File(s) | Tests | Coverage |
|-------|---------|-------|----------|
| US1 — Observability | `test_middleware.py`, `test_health.py` | 79 | ~97% (gap: `StrictResponseLimitingMiddleware` tool-level limit) |
| US2 — Authentication | `test_token_passthrough.py`, `test_auth.py`, `test_config.py` | 105 | 100% |
| US3 — Read-Only | `test_read_only.py`, `test_middleware.py` | 13+ | 100% |
| US4 — Auto Branching | `test_branch_pattern.py`, `test_tools.py` | 34 | ~95% (gap: `get_or_create_session_branch()` lazy flow) |
| Other | `test_server_env.py`, `test_prompts.py`, `test_get_nodes_pagination.py` | 22 | — |

### Integration Tests (26 tests — future, testcontainers)

| Story | File | Tests | What it validates |
|-------|------|-------|-------------------|
| US1 | `test_health_e2e.py` | 4 | Health/metrics endpoints against real Infrahub |
| US2 | `test_auth_passthrough.py` | 5 | Token/basic auth against real Infrahub |
| US2 | `test_oidc_flow.py` | 3 | Full OIDC flow with real Keycloak |
| US3 | `test_read_only_e2e.py` | 3 | Write filtering against real server |
| US4 | `test_branch_lifecycle.py` | 5 | Branch creation/reuse/protection in real Infrahub |
| Cross | `test_full_lifecycle.py` | 2 | Full stack + concurrent credential isolation |
| Infra | `conftest.py` | — | Testcontainers fixtures (Infrahub, Keycloak) |

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (config, AppContext)
2. Complete Phase 2: Foundational (middleware framework, ContextVars, error handling)
3. Complete Phase 3: User Story 1 (observability stack)
4. **STOP and VALIDATE**: Structured logs, health check, metrics all working
5. Deploy/demo if ready

### Incremental Delivery

1. Setup + Foundational → Config validated, middleware composes
2. Add US1 (Observability) → Structured logs, health, metrics (MVP!)
3. Add US2 (Authentication) → Per-user auth, credential isolation
4. Add US3 (Read-Only) → Write tool filtering, defense-in-depth
5. Add US4 (Auto Branching) → Session branches, default branch protection
6. Each story adds value without breaking previous stories

### Integration Test Rollout

1. Add testcontainers infra (T047–T050) — gated behind `pytest -m integration`
2. Start with US1 health tests (simplest: only Infrahub container needed)
3. Add US2 passthrough tests (Infrahub container + API tokens)
4. Add OIDC tests (Keycloak container — most complex setup)
5. Add US3/US4 tests (reuse existing containers)
6. Add cross-cutting lifecycle test last (depends on all stories)

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: US1 (Observability) + US3 (Read-Only)
   - Developer B: US2 (Authentication) + US4 (Auto Branching)
3. Stories complete and integrate independently
