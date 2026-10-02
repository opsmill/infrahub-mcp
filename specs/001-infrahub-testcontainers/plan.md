# Implementation Plan: Infrahub Testcontainers Integration Tests

**Branch**: `001-infrahub-testcontainers` | **Date**: 2026-05-22 (updated 2026-06-15) | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-infrahub-testcontainers/spec.md`

## Summary

Add an integration test tier to the Infrahub MCP server that exercises the MCP surface (tools, resources, prompts) end-to-end against a real Infrahub instance provisioned via the upstream `infrahub-testcontainers` pytest fixture. One Infrahub Docker stack is spun up per test session and a fresh Infrahub branch is created per test for isolation (per the [clarification](./spec.md#clarifications) recorded 2026-05-22). The integration suite lives under `tests/integration/`, is opt-in via a `integration` pytest marker (default `uv run pytest` runs only unit tests, preserving the fast inner loop), and runs as a dedicated GitHub Actions job gating PRs to `stable`.

Per the 2026-06-15 clarifications: tests drive the server via the **in-process FastMCP `Client`** against the module-level `mcp` server instance — the Starlette ASGI auth/OIDC/transport layer is bypassed (no OIDC issuer container needed), while FastMCP-level middleware (incl. `ReadOnlyMiddleware` write-gating, audit, caching) is still exercised. The suite also includes a dedicated **version-compatibility check** (FR-013) that asserts the running Infrahub version against the pinned/SDK-supported range and reports a distinct, clearly-labeled result so version drift is distinguishable from a functional regression.

## Technical Context

**Language/Version**: Python 3.13 (matches project)
**Primary Dependencies**:

- Existing: `infrahub-sdk>=1.20.0`, `fastmcp>=3.2.0`, `pytest>=8.4.1`, `pytest-asyncio>=1.1.0`
- New (dev group): `infrahub-testcontainers` (PyPI, pinned to a specific Infrahub minor; ships `TestInfrahubDocker` base class and a docker-compose stack)

**Storage**: N/A. The Infrahub container provisions its own Neo4j/Memgraph + Redis + task-worker stack via `infrahub-testcontainers`'s embedded `docker-compose.test.yml`.

**Testing**:

- Unit suite remains untouched at `tests/unit/`, runs without Docker.
- Integration suite at `tests/integration/`, requires Docker, opt-in via `-m integration` or `pytest tests/integration`.
- Session-scoped Infrahub container (one per `pytest` invocation); function-scoped per-test Infrahub branch.
- Tests drive the MCP server via the in-process FastMCP `Client` against the module-level `mcp` server (ASGI auth/OIDC/transport bypassed; FastMCP-level middleware retained).

**Target Platform**: Linux (CI: `ubuntu-latest`), macOS/Linux developer machines with Docker engine reachable.

**Project Type**: Single project (library/MCP server).

**Performance Goals**:

- Full integration suite under 10 minutes locally (SC-001) — budget: container startup ~60–120s, ~15–25 tests at <10s each.
- Default `uv run pytest` wall-clock unchanged within 5% (SC-002) — achieved by keeping integration tests off the default path.

**Constraints**:

- Docker engine MUST be available for integration runs; suite MUST fail fast with a clear message otherwise (FR-007).
- Concurrent runs on the same host MUST not collide (FR-009); `infrahub-testcontainers` already allocates random host ports via `tmpdir_factory`.
- Infrahub image version MUST be pinned and recorded (FR-008); we pin via `INFRAHUB_TESTING_IMAGE_VER` in CI and as a documented default for local runs.

**Scale/Scope**:

- ~15–25 integration tests covering: schema resource, branch listing/resource, node read tools (get/list with filters/pagination), GraphQL tool, one representative write tool gated on the existing `read_only=false` config, plus a version-compatibility check (FR-013) asserting the running Infrahub version against the pinned/SDK-supported range.
- Single Infrahub session per CI job; one Infrahub branch per test.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

Gates derived from `.specify/memory/constitution.md` v1.0.0:

| Principle | Gate | Status |
|-----------|------|--------|
| I. MCP Protocol Compliance | Tests exercise the MCP surface as protocol-compliant clients; no protocol shortcuts. | Pass |
| II. Infrahub SDK Integration | Test setup/teardown uses the SDK (`InfrahubClient`) for branch and fixture data ops; no raw HTTP. | Pass |
| III. Branch-Safe by Default | Isolation model IS Infrahub branches — directly reinforces the principle; the one write-tool test runs on its own per-test branch. | Pass |
| IV. Type Safety & Explicit Contracts | Fixtures and tests are fully typed; mypy is part of the existing `uv run pre-commit run` gate and will be applied to `tests/integration/`. | Pass |
| V. Test Discipline | Feature ADDS a test tier; each integration test atomic, parametrized variants where appropriate, mirrors source structure (`tests/integration/test_*.py` parallels `src/infrahub_mcp/tools/*.py` and `src/infrahub_mcp/resources/*.py`). | Pass |
| VI. Security & Input Boundaries | Fixture credentials are the upstream `infrahub-testcontainers` initial admin token (well-known test token, never a prod secret); no real Infrahub credentials enter tests. Tests drive the server via the in-process FastMCP client, so the ASGI auth/OIDC layer is bypassed (no OIDC issuer needed) while FastMCP-level middleware — including `ReadOnlyMiddleware` write-gating — is still exercised. | Pass |
| VII. Simplicity & Maintainability | Reuse upstream `infrahub-testcontainers`; do NOT reimplement container orchestration. No new abstractions over pytest. | Pass |

No gate violations require Complexity Tracking entries.

## Project Structure

### Documentation (this feature)

```text
specs/001-infrahub-testcontainers/
├── plan.md              # This file
├── research.md          # Phase 0 — resolves deferred clarifications
├── data-model.md        # Phase 1 — fixture data model & lifecycle
├── quickstart.md        # Phase 1 — how to run integration tests locally
├── contracts/
│   └── integration-test-surface.md  # MCP surface covered by integration tests
└── checklists/
    └── requirements.md  # already exists from /speckit-specify
```

### Source Code (repository root)

```text
tests/
├── unit/                          # existing — unchanged
│   ├── conftest.py
│   ├── test_*.py
│   └── ...
└── integration/                   # NEW
    ├── __init__.py
    ├── conftest.py                # session-scoped Infrahub container, per-test branch fixture, in-process FastMCP mcp_client fixture
    ├── fixtures/
    │   └── schema_minimal.yml     # minimal Infrahub schema seeded once per session
    ├── test_schema_resource.py    # one file per MCP surface area
    ├── test_branches_resource.py
    ├── test_node_tools.py
    ├── test_graphql_tool.py
    ├── test_write_tool.py         # gated; runs only when write tools enabled
    └── test_version_compat.py     # FR-013: assert running Infrahub version vs pinned/SDK range

pyproject.toml                     # register `integration` marker; ensure addopts behavior intentional
.github/workflows/ci.yml           # add `integration-tests` job (Docker-enabled ubuntu runner)
```

**Structure Decision**: Single project layout. The existing `tests/unit/` directory is preserved untouched; the new `tests/integration/` directory sits alongside it. Selection is by directory + marker, not by configuration acrobatics:

```bash
uv run pytest tests/unit                        # fast, no Docker (default unchanged)
uv run pytest tests/integration -m integration  # integration, requires Docker
uv run pytest                                   # default; excludes integration via `-m 'not integration'`
```

## Complexity Tracking

No violations to track. All Constitution gates pass. The MCP drive-layer question (formerly a deferred clarification) is resolved by the 2026-06-15 clarification: integration tests use the in-process FastMCP client — the ASGI auth/OIDC layer is bypassed while FastMCP-level middleware is retained — see `research.md` D2.
