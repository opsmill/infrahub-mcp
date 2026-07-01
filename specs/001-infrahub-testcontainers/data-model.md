# Phase 1 Data Model: Integration Test Fixtures

**Feature**: 001-infrahub-testcontainers
**Date**: 2026-05-22

Integration tests do not introduce production data. The "data model" here is the lifecycle of test fixtures and the seeded Infrahub state.

## Entities

### IntegrationTestSession

| Attribute | Type | Description |
|-----------|------|-------------|
| `session_id` | `str` (pytest-generated) | Unique per `pytest` invocation. |
| `infrahub_compose` | `InfrahubDockerCompose` | The upstream `infrahub-testcontainers` compose handle. |
| `infrahub_ports` | `dict[str, int]` | Service-name → host port mapping returned by `infrahub_app` fixture. |
| `infrahub_address` | `str` | `http://localhost:{infrahub_port}` resolved at fixture setup. |
| `admin_token` | `str` | The upstream testcontainers initial admin token (`PROJECT_ENV_VARIABLES["INFRAHUB_TESTING_INITIAL_ADMIN_TOKEN"]`). |
| `seeded` | `bool` | True after baseline schema + nodes are loaded. |

**Lifecycle**: Created on first integration-test collection in a `pytest` run; destroyed at session teardown. Scope = `session`.

**Identity**: `session_id`.

**Transitions**: `created → starting → ready → seeded → in-use → tearing-down → destroyed`.

### PerTestBranch

| Attribute | Type | Description |
|-----------|------|-------------|
| `name` | `str` | Generated as `test-{nodeid-slug}-{uuid8}`. |
| `parent` | `str` | Always `main` (the seeded baseline). |
| `created_at` | `datetime` | Set by fixture setup. |
| `deleted_at` | `datetime \| None` | Set by fixture teardown. |

**Lifecycle**: Created at the start of each test (`function`-scoped fixture); deleted at test teardown regardless of pass/fail (try/finally).

**Identity**: `name`. Branch name uniqueness is required by Infrahub.

**Validation**: Branch name MUST satisfy Infrahub's branch-name character set (alphanumeric, hyphens, underscores, dots, slashes). The fixture generates names that conform.

**Relationships**:

- Each `PerTestBranch` belongs to exactly one `IntegrationTestSession`.
- Each test function consumes exactly one `PerTestBranch`.

### McpServerUnderTest

| Attribute | Type | Description |
|-----------|------|-------------|
| `config` | `ServerConfig` | A `ServerConfig` instance pointed at the session's Infrahub address, write tools enabled (`read_only=false`). The Infrahub credential is the testcontainers admin token (`INFRAHUB_API_TOKEN`). No HTTP auth mode participates — the ASGI layer is not built. |
| `server` | `FastMCP` | The composed `mcp` server instance from `src/infrahub_mcp/server.py`, configured for the session with FastMCP-level middleware via `configure_middleware()`. |
| `client` | `fastmcp.Client` | In-process FastMCP client over the in-memory transport (`Client(mcp)`); no ASGI app, no HTTP, no auth/OIDC layer. FastMCP-level middleware (ReadOnly, audit, caching, error handling) still runs. |

**Lifecycle**: Built once per session (after the Infrahub container is ready and seeded). The same MCP server instance serves all tests; per-test isolation comes from the `PerTestBranch`, not from spinning up a new MCP server per test. The `read_only=true` write-rejection contract (contracts T4) uses a separate server instance configured with `read_only=true`; this is valid because `ReadOnlyMiddleware` is a FastMCP-level middleware that runs under the in-memory transport.

**Identity**: Singleton per session (the `read_only=true` variant is a separate, short-lived instance).

**Transitions**: `unbuilt → built → ready → torn-down`.

### SeedSchema

| Attribute | Type | Description |
|-----------|------|-------------|
| `path` | `Path` | `tests/integration/fixtures/schema_minimal.yml`. |
| `node_kinds` | `list[str]` | Names of the kinds the schema defines (e.g., `LocationSite`, `Device`). |
| `loaded_at` | `datetime` | When the schema was loaded into Infrahub (once per session). |

**Lifecycle**: Loaded once during session setup, before any per-test branch is created.

**Validation**: The schema MUST be loadable by the Infrahub SDK against the session's Infrahub container; failure to load aborts the session.

### SeedNodes

A small fixed set of baseline node instances created on `main` once per session. Exact set is defined in `tests/integration/fixtures/seed.py` (Python so the SDK can be used directly).

| Attribute | Type | Description |
|-----------|------|-------------|
| `kind` | `str` | One of the kinds in `SeedSchema.node_kinds`. |
| `attributes` | `dict[str, Any]` | Concrete values per kind. |
| `id` | `str` (assigned by Infrahub) | Captured at seed time, available to tests. |

**Lifecycle**: Created once per session on `main`. Never mutated by tests (tests mutate per-test branches).

## Validation Rules

- The test harness MUST verify Docker is reachable before attempting to start the Infrahub compose; failure produces a clear error referencing FR-007.
- The test harness MUST verify the Infrahub container is ready (HTTP 200 on `/api/schema`) before yielding the session fixture.
- The test harness MUST clean up every `PerTestBranch` it creates, including on test interruption (use `addfinalizer` / `try-finally`).
- Concurrent sessions MUST NOT share `IntegrationTestSession` state — each `pytest` invocation gets its own.

## State Transitions (sequence)

```text
pytest collects integration tests
  → IntegrationTestSession.created
    → infrahub_compose.start()          [upstream fixture]
      → IntegrationTestSession.ready    [HTTP probe passes]
        → SeedSchema.load()             [SDK call]
          → SeedNodes.create()          [SDK calls on main]
            → IntegrationTestSession.seeded
              → McpServerUnderTest.build()
                ↓
  for each test:
    PerTestBranch.create()              [SDK: branch_create off main]
      run test against MCP server, scoped to PerTestBranch
    PerTestBranch.delete()              [SDK: branch_delete, in try/finally]
  end for
                ↓
  → McpServerUnderTest.teardown()
  → infrahub_compose.stop()              [upstream fixture]
  → IntegrationTestSession.destroyed
```

## Out of Scope

- Production Infrahub data: never touched by integration tests.
- Generated MCP audit / log artifacts: emitted by the running MCP server but not part of the data model under test in v1 (see research.md D3).
