# Phase 0 Research: Infrahub Testcontainers Integration Tests

**Feature**: 001-infrahub-testcontainers
**Date**: 2026-05-22

This document resolves the technical unknowns from the plan's Technical Context. The 2026-06-15 `/speckit-clarify` session answered the test-separation, MCP drive-layer, and version-drift questions directly in [spec.md → Clarifications](./spec.md#clarifications); D2, D6, and D11 below are aligned with those answers. Each section is a Decision / Rationale / Alternatives record.

---

## D1. Test isolation model (resolved during clarification — recorded here for completeness)

**Decision**: One Infrahub container per pytest session + one fresh Infrahub branch per test (created at fixture setup, deleted at teardown).

**Rationale**: Recorded in [spec.md → Clarifications](./spec.md#clarifications). Branch-per-test leverages Infrahub's native versioning as the isolation primitive, avoids the ~60–120s container-startup cost per test, and matches Constitution principle III ("Branch-Safe by Default").

**Alternatives considered**:

- Container-per-test: too slow given SC-001's 10-minute budget.
- Reseed/reset per test: brittle, has to enumerate all mutations to undo them.
- No isolation: fails FR-011 (deterministic starting state).

---

## D2. MCP server drive layer & authentication during integration tests

**Decision** (clarified 2026-06-15): Drive the MCP server via the **in-process FastMCP `Client`** (FastMCP in-memory transport) against the module-level `mcp` server instance from `src/infrahub_mcp/server.py`. The Starlette **ASGI auth/OIDC/transport layer is bypassed entirely** — no ASGI app is built and no HTTP auth mode (`none`/`oidc`/passthrough) participates, because that layer never runs under the in-memory transport. The MCP-server-to-Infrahub credential is the upstream testcontainers admin token, configured on `ServerConfig` (`INFRAHUB_API_TOKEN`).

Crucially, FastMCP-level middleware (those subclassing `fastmcp.server.middleware.Middleware` with `on_call_tool` hooks — `ReadOnlyMiddleware`, `AuditMiddleware`, caching, rate-limiting, error handling) **still runs** under the in-memory transport, so write-gating and error-masking behavior remain under integration coverage. Only the HTTP/ASGI layer (`_CredentialsPassthroughASGI`, `_OAuthDiscoveryInterceptASGI`, OIDC discovery) is skipped.

**Rationale**:

- The feature under integration test is the MCP↔Infrahub contract, not the HTTP auth/transport layer. The unit suite already exhaustively covers OIDC, token-passthrough, and basic-passthrough (`test_auth.py`, `test_token_passthrough.py`, `test_middleware.py`).
- The in-process client is the simplest possible harness: no ASGI app construction, no auth ceremony, no fake OIDC issuer container — keeping each test focused on the Infrahub interaction.
- Because FastMCP-level middleware still executes, `ReadOnlyMiddleware` write-gating (Principle III) is genuinely exercised end-to-end against a real Infrahub, not mocked.

**Constitution alignment**: Principle VI (auth validated at startup) is unaffected — startup auth validation is unit-tested; the integration suite simply does not stand up the HTTP transport. Principle I (MCP protocol compliance) is preserved: the FastMCP in-memory client speaks the MCP protocol to the same server object a network client would.

**Alternatives considered**:

- Full ASGI app via `build_app(config)` + in-process `httpx` client in `none` auth mode (the pre-clarification approach): rejected 2026-06-15 — exercises the ASGI auth layer the unit suite already covers and forces auth-mode bookkeeping into every fixture without new MCP↔Infrahub signal.
- HTTP transport with a fake OIDC issuer: rejected — adds containers and complexity without new signal.
- Token-passthrough smoke test: may be added later as a thin unit-level or HTTP smoke test if the boundary feels too sharp; out of scope for v1.

---

## D3. MCP surface coverage scope for integration tests

**Decision**: Cover the following surface in v1:

1. `schema` resource (MCP resource read) — verify schema content matches the seeded Infrahub schema.
2. `branches` resource (MCP resource read) — verify branches list includes `main` plus per-test branch.
3. Node read tools: `get_node`, `get_nodes` (with at least one filter and one paginated case).
4. `graphql_query` tool — one read query against the seeded data.
5. One write tool (`create_node` or equivalent) — gated by `read_only=false` and isolated to the per-test branch.

**Out of scope for v1** (may be added later, recorded here for clarity): prompt templates, OpenTelemetry traces, rate limiting middleware behavior, response caching behavior, audit middleware output. The unit suite already covers these; adding integration coverage is incremental and not blocking.

**Rationale**: This is the minimum surface that catches MCP↔Infrahub contract drift (schema shape, branch model, node response shape, GraphQL response shape, write path). It maps directly to FR-005.

**Alternatives considered**:

- Cover every tool/resource/prompt: rejected — combinatorial growth, diminishing returns, would blow past 10-minute budget.
- Cover only reads: rejected — write path is the most consequential for branch-safety regression detection (Principle III).

---

## D4. CI trigger model and gating

**Decision**: Add a new GitHub Actions job `integration-tests` in `.github/workflows/ci.yml`:

- Triggers: same `pull_request` + push to `stable`/`develop` as the existing `ci.yml` workflow.
- Conditional on `files-changed.outputs.mcp == 'true'` (existing path filter) to avoid spending CI minutes on docs-only PRs.
- Runs on `ubuntu-latest` (Docker available by default).
- Steps: setup-python + setup-uv → `uv sync --all-groups` → `uv run pytest tests/integration -m integration --tb=short`.
- Configured as a required check in branch protection for `stable` (separate, post-merge configuration step — documented in `quickstart.md`).

**Rationale**: Reuses the existing `files-changed` filter and `prepare-environment` job that the project already invests in. New job, not extended `python-lint` job, because failure modes and timing are very different (10 minutes vs. 1 minute).

**Alternatives considered**:

- On-demand label-triggered: rejected — defeats SC-003's "100% of PRs" goal.
- Run inside the existing test job: rejected — couples slow integration to the fast lint feedback the project already has.
- Self-hosted runner with Docker preinstalled: rejected — `ubuntu-latest` already ships Docker; no preinstall needed.

---

## D5. Infrahub image version pinning policy

**Decision**: Pin `infrahub-testcontainers` to a specific minor version in `pyproject.toml` (e.g., `infrahub-testcontainers~=1.9`). The Infrahub container image version is derived from this package by default (the package's `__version__` is used unless `INFRAHUB_TESTING_IMAGE_VER` overrides it). CI sets `INFRAHUB_TESTING_IMAGE_VER` to a single specific version to remove drift between local and CI. A monthly Renovate/Dependabot PR proposes the version bump; bumps are reviewable like any other dependency change.

**Rationale**: Satisfies FR-008 (pinned, reviewable, reproducible). Single-version (no matrix) keeps CI minutes in check; we will add matrix testing if/when we ship Infrahub-version-conditional code paths.

**Alternatives considered**:

- Float to latest: rejected — non-reproducible, makes "integration test failure" indistinguishable from "Infrahub released a breaking change."
- Multi-version matrix (e.g., latest + N-1): rejected for v1 — 2x CI cost without a current need; revisit when we explicitly support multiple Infrahub versions.

---

## D6. Marker, addopts, and default-suite separation

**Decision**:

- Register `integration` as a custom marker in `pyproject.toml` under `[tool.pytest.ini_options]`.
- Apply `@pytest.mark.integration` to every test in `tests/integration/` via an `pytestmark = pytest.mark.integration` module-level statement in each integration test file (or via a `conftest.py`-level autouse marker).
- Keep the default `addopts = "-p no:pytest-infrahub"` so the infrahub pytest plugin stays inactive for the fast unit loop (it pulls in Docker/Infrahub machinery unit tests must not need). The integration command re-enables the plugin (e.g. `uv run pytest -p pytest-infrahub tests/integration`, or scoped via a `tests/integration`-local config) since the `infrahub-testcontainers` fixtures are surfaced through it. The exact re-enable mechanism (CLI flag vs. integration-local `addopts`) is settled in implementation; the contract is: **default = plugin off, integration = plugin on**, matching the spec clarification.
- Add a default `-m 'not integration'` selector to keep `uv run pytest` (no args) running only unit tests. Override locally with `uv run pytest -m integration` or `uv run pytest tests/integration`.

**Rationale**: Satisfies SC-002 (unit-suite wall-clock unchanged), FR-002 (suites separated), and FR-003 (single command). Mirrors a common pytest idiom widely understood by contributors.

**Alternatives considered**:

- Separate top-level `integration-tests/` directory outside `tests/`: rejected — splits discoverability.
- Conftest-only opt-in (no marker): rejected — markers are the standard pytest mechanism and play well with CI filters and IDE plugins.

---

## D7. Test failure observability

**Decision**: On test failure, the suite must surface (a) the failing test name and the Pytest assertion, (b) the last ~200 lines of `infrahub-server` and `task-worker` container logs (the upstream `TestInfrahubDocker.infrahub_app` fixture already emits these on per-class teardown when failures occurred), and (c) the branch name used for the failing test, so a developer can reproduce against the same branch if the container is left running for ad-hoc inspection (`--keep-containers` style flag — see D8).

**Rationale**: Satisfies FR-012.

**Alternatives considered**:

- Full container logs on every failure: rejected — flood. ~200 lines is enough for most signal.
- No log dump (rely on test assertion only): rejected — most integration failures need backend log context to diagnose.

---

## D8. Local developer ergonomics

**Decision**: Document the following in `quickstart.md`:

- `uv run pytest tests/integration` — full integration run.
- `INFRAHUB_TESTCONTAINERS_KEEP=1 uv run pytest tests/integration` — leave containers up on exit for inspection (implemented via a small env-var check in the session-scoped fixture's teardown).
- Per-test selection: `uv run pytest tests/integration/test_node_tools.py::test_get_nodes_with_filter`.

**Rationale**: Common developer flows. The `KEEP=1` toggle is the lowest-cost way to satisfy the implicit "let me poke at it when it breaks" workflow without violating FR-004 by default (default still tears down).

**Alternatives considered**:

- Always tear down regardless: rejected — too costly for ad-hoc debugging.
- Wrapper CLI command: rejected — adds dependency surface; env-var toggle is enough.

---

## D9. Test data seeding strategy

**Decision**: One session-scoped fixture seeds a minimal schema (`tests/integration/fixtures/schema_minimal.yml`) and a small set of baseline nodes into the `main` branch immediately after container readiness. Per-test branches are created off this baseline; mutations in tests stay on the per-test branch. Tests never modify `main` after seeding.

**Rationale**: Constitution III. Also makes branch isolation effective — if mutations leaked to `main`, branch-per-test wouldn't isolate them.

**Schema scope**: Keep the seeded schema *minimal* — just enough to exercise the MCP surface. Reuse an existing demo schema fragment (such as the SDK's `LocationSite` shape already referenced in `tests/unit/conftest.py:locationsite_filters`) so unit and integration fixtures share a mental model.

**Alternatives considered**:

- Use Infrahub's full demo schema: rejected — slow to load, more failure modes unrelated to MCP.
- Per-test schema reseeding: rejected — schemas are session-stable; branch is the right unit.

---

## D10. Concurrent test runs on the same host (FR-009)

**Decision**: Rely on `infrahub-testcontainers`' existing behavior: it allocates a per-session `tmp_directory` via `tmpdir_factory`, creates a uniquely-named docker-compose project under that directory, and lets Docker assign random host ports. No additional work needed in our test code.

**Rationale**: The upstream fixture already isolates by project name and ephemeral ports. Two concurrent `uv run pytest tests/integration` invocations on the same host will get two independent Infrahub stacks.

**Risk**: If a developer runs *many* parallel sessions, Docker resource exhaustion (memory, port range) becomes the limit, not name collisions. Documented in `quickstart.md`.

---

## D11. Infrahub version-compatibility check (FR-013)

**Decision** (clarified 2026-06-15): Add one dedicated integration test (`tests/integration/test_version_compat.py`) that reads the running Infrahub version (via the SDK — e.g. the `/api/version` info the SDK surfaces) and asserts it falls within the version range the pinned `infrahub-sdk` supports. On mismatch it emits a **clearly-labeled, distinct result** — an `xfail`/`skip` whose `reason` names both versions, or a dedicated assertion failure whose message is unmistakably "version drift", not a functional regression.

**Rationale**: Satisfies FR-013 and resolves the "Infrahub version drift" edge case. A single focused check means a version bump that outpaces the SDK shows up as one obviously-labeled signal in CI output instead of a confusing scatter of functional-test failures. Low cost (one test), high triage value.

**Mechanism notes**:

- The check is itself marked `integration` (it needs the running container) and runs early so its signal precedes functional failures.
- Source of truth for the "supported range" is the pinned `infrahub-sdk` version's declared compatibility (documented in `quickstart.md`); when no machine-readable range is available, assert against the pinned `INFRAHUB_TESTING_IMAGE_VER` and treat divergence as drift.
- Reports via pytest's standard mechanisms; no new reporting infrastructure.

**Alternatives considered**:

- Documentation + manual triage only: rejected — relies on a human noticing; the spec promises the suite itself distinguishes drift.
- Drop the expectation: rejected — loses the edge case the spec commits to.

---

## Summary

All NEEDS CLARIFICATION items resolved. D2 (drive layer), D6 (separation), and D11 (version-compat check) reflect the 2026-06-15 clarifications. No item deferred to Phase 1.

Phase 0 status: **complete**.
