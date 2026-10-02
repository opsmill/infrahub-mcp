# Feature Specification: Infrahub Testcontainers Integration Tests

**Feature Branch**: `001-infrahub-testcontainers`
**Created**: 2026-05-22
**Status**: Draft
**Input**: User description: "I want to use infrahub testcontainers to run integration tests"

## Clarifications

### Session 2026-05-22

- Q: Which isolation model should each integration test run against? → A: One Infrahub container per session + new Infrahub branch per test

### Session 2026-06-15

- Q: How should integration tests be separated from unit tests so the default run stays Docker-free? → A: A dedicated `tests/integration/` directory AND a `@pytest.mark.integration` marker; the default run excludes integration tests (`-m "not integration"`) and keeps the infrahub pytest plugin disabled, while the integration run targets the directory with the plugin enabled.
- Q: At what layer should the integration tests drive the MCP server against the real Infrahub? → A: Via the in-process FastMCP client against the server instance (auth/transport middleware bypassed), keeping the suite focused on the Infrahub-facing contract; the middleware/auth layers retain their existing unit coverage. No OIDC provider container is required.
- Q: How should the suite make Infrahub version drift distinguishable from a real product regression? → A: A dedicated version-compatibility check reads the running Infrahub version and asserts it matches the pinned/SDK-supported range, emitting a clearly-labeled distinct result (failure or xfail/skip) so drift is not confused with a functional regression.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Validate MCP server behavior against a real Infrahub (Priority: P1)

A maintainer changes the MCP server (for example, the schema resource, a node tool, or the GraphQL tool) and wants confidence that the change still works end-to-end against a real, running Infrahub — not just against mocks. They run the integration test suite locally; the suite provisions an ephemeral Infrahub instance, exercises the MCP server against it, and reports pass/fail.

**Why this priority**: This is the core value of the feature. Today the test suite is entirely unit-level with mocked Infrahub interactions, so contract drift between the MCP server and a real Infrahub (schema changes, SDK behavior, response shapes) is invisible until a user hits it. Catching this in CI/local dev is the whole point.

**Independent Test**: Can be fully validated by running a single command (e.g., the integration test entry point) on a developer machine with Docker available, and observing that an Infrahub container starts, integration tests execute against it, the container is torn down, and a clear pass/fail summary is produced.

**Acceptance Scenarios**:

1. **Given** a clean developer machine with Docker available and project dependencies installed, **When** the maintainer invokes the integration test command, **Then** an Infrahub instance is provisioned, integration tests run against it, all containers are torn down on exit, and the test result is reported.
2. **Given** a regression has been introduced in the MCP server's interaction with Infrahub (for example, a tool now sends a malformed query), **When** the integration test suite runs, **Then** at least one integration test fails with a clear, actionable message pointing to the regression.
3. **Given** the integration test suite has finished (whether passing or failing), **When** the maintainer inspects the local Docker state, **Then** no Infrahub containers, networks, or volumes created by the test run remain.

---

### User Story 2 - Run integration tests in CI on every change (Priority: P2)

A maintainer opens a pull request. The CI pipeline automatically runs the integration test suite against an ephemeral Infrahub instance and blocks merge if any integration test fails. PR authors and reviewers can see the integration test outcome alongside unit test results.

**Why this priority**: Local-only integration tests catch regressions for the maintainer who runs them, but only CI enforcement ensures every contribution is validated. This builds on Story 1 and is unlocked once the local flow is reliable.

**Independent Test**: Can be validated by opening a pull request that intentionally breaks the MCP server's interaction with Infrahub and observing that the CI integration test job fails and prevents merge under the project's branch protection rules.

**Acceptance Scenarios**:

1. **Given** a pull request introducing a change to MCP server code, **When** CI runs, **Then** the integration test job executes and its result is visible on the pull request.
2. **Given** an integration test fails in CI, **When** a reviewer inspects the job output, **Then** they can identify which test failed and see enough log context to begin diagnosis without re-running locally.
3. **Given** an integration test job completes (pass or fail), **When** the CI runner is reused for the next job, **Then** no leftover Infrahub state from the previous run interferes with subsequent jobs.

---

### User Story 3 - Keep the fast unit-test loop intact (Priority: P2)

A maintainer working on a non-integration change wants the existing fast unit test loop (`uv run pytest`) to remain quick and dependency-free. Integration tests should be opt-in (or clearly separated) so day-to-day development is not slowed by container startup.

**Why this priority**: Equal priority with CI enforcement because the fast inner-loop is a known productivity gain that integration tests must not erode. Without this guarantee, maintainers will start skipping or disabling tests.

**Independent Test**: Can be validated by running the default test command and observing that no Docker containers are started and total runtime stays comparable to the current unit-test baseline (within a small tolerance for any shared fixtures).

**Acceptance Scenarios**:

1. **Given** the default test command, **When** it runs, **Then** only unit tests execute and no Docker containers are started.
2. **Given** the integration-test command (or marker/flag), **When** it runs, **Then** integration tests execute and unit tests may also run, but the developer has explicitly opted into the longer run.
3. **Given** documentation describing how to run tests, **When** a new contributor reads it, **Then** they understand which command runs unit tests, which runs integration tests, and what prerequisites each has.

---

### Edge Cases

- **Docker unavailable**: When a developer runs the integration suite on a machine without a working Docker engine, the suite must fail fast with a clear, actionable message naming the missing prerequisite — not hang or produce confusing internal errors.
- **Port conflicts**: When the host already has a service occupying a port the Infrahub container would otherwise use, the integration suite must either pick an alternate port automatically or fail with a clear conflict message identifying the port.
- **Slow container startup**: When the Infrahub container takes longer than usual to become ready, the suite must wait for a readiness signal up to a defined timeout, then fail with a clear timeout message rather than running tests against a not-yet-ready instance.
- **Test interrupted (Ctrl-C, CI cancel)**: When the test run is interrupted partway through, container cleanup must still occur so the host (or CI runner) is left in a clean state.
- **Image pull failure / offline**: When the required Infrahub image cannot be pulled (no network, registry outage), the suite must fail with a clear message naming the unreachable image, not a generic Docker error.
- **Parallel test runs**: When two integration test runs are started concurrently on the same host (e.g., two developers, or CI matrix), they must not collide on container names, networks, or ports.
- **Infrahub version drift**: When the pinned Infrahub image version diverges from the version the project's SDK targets, the suite must surface this via a dedicated version-compatibility check (see FR-013) that reports a distinct, clearly-labeled result rather than a generic test failure, so it is distinguishable from a real product regression.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The project MUST provide an integration test suite that exercises the MCP server end-to-end against a real, ephemeral Infrahub instance provisioned via containers.
- **FR-002**: The integration test suite MUST be separated from the existing unit test suite using BOTH a dedicated `tests/integration/` directory and a `@pytest.mark.integration` marker. The default test command MUST exclude integration tests (e.g., `-m "not integration"`) and keep the infrahub pytest plugin disabled, so it continues to run without requiring Docker or network access; the integration command MUST target the integration directory with the plugin enabled.
- **FR-003**: The integration test suite MUST be invocable by a single, documented command that handles container provisioning, test execution, and teardown.
- **FR-004**: Containers, networks, and volumes created by an integration test run MUST be torn down on suite exit, including the case where tests fail or the run is interrupted.
- **FR-005**: The integration test suite MUST cover the externally observable MCP surface area that depends on Infrahub: at minimum the schema resource, branch listing, node read tools, the GraphQL tool, and one representative write tool (gated by the existing write-tools enablement flag). Tests MUST drive the MCP server via the in-process FastMCP client against the server instance (auth/transport middleware bypassed) so the suite stays focused on the Infrahub-facing contract; no OIDC provider is provisioned, and the middleware/auth layers retain their existing unit coverage.
- **FR-006**: The integration test suite MUST run in CI on every pull request and its result MUST be reported as a distinct check that can gate merges.
- **FR-007**: The integration test suite MUST fail fast with a clear, human-readable message when its prerequisites (e.g., Docker engine availability, required image) are not met.
- **FR-008**: The integration test suite MUST pin the Infrahub container image to a specific, recorded version so test results are reproducible across machines and over time, and so an image version bump is an explicit, reviewable change.
- **FR-009**: The integration test suite MUST tolerate concurrent runs on the same host without collisions on container names, networks, or ports.
- **FR-010**: Documentation MUST describe how to run integration tests locally, the prerequisites, and how the suite differs from unit tests.
- **FR-011**: The suite MUST provision exactly one Infrahub instance per test session and isolate individual tests by creating a dedicated Infrahub branch per test (deleted on test teardown), so every test runs against a known, deterministic starting state independent of test order.
- **FR-012**: The integration test suite MUST surface a clear, actionable failure message when an integration test fails, including enough context (test name, observed vs. expected, relevant Infrahub state) to begin diagnosis without re-running.
- **FR-013**: The integration test suite MUST include a dedicated version-compatibility check that reads the running Infrahub version and asserts it matches the pinned/SDK-supported range, emitting a clearly-labeled, distinct result (failure or `xfail`/skip) so version drift is distinguishable from a functional product regression.

### Key Entities

- **Integration test suite**: A new, separately invocable body of tests living in a dedicated `tests/integration/` directory and tagged with the `@pytest.mark.integration` marker, so the two suites can be run independently.
- **Ephemeral Infrahub instance**: A real Infrahub deployment provisioned once per test session inside Docker containers, used as the system-under-test's backend, and destroyed at the end of the session.
- **Per-test Infrahub branch**: An Infrahub branch created at the start of each test (off a clean, session-seeded baseline) and deleted at teardown; the unit of test isolation that lets concurrent tests share a single Infrahub container.
- **Test fixture data**: Deterministic seed data loaded into the Infrahub instance once per session (schemas, baseline branches, sample nodes) so per-test branches have a known starting state.
- **CI integration job**: The CI pipeline step responsible for executing the integration suite, reporting its result, and ensuring its outcome can gate pull-request merges.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A maintainer with Docker installed can run the integration test suite from a clean checkout with a single documented command in under 10 minutes (including container startup, all tests, and teardown).
- **SC-002**: The default unit test command's wall-clock runtime increases by less than 5% after this feature ships, measured on a representative developer machine.
- **SC-003**: 100% of pull requests opened against the main branch trigger the CI integration job, and a failing integration job blocks merge under the project's branch protection rules.
- **SC-004**: At least one regression caused by drift between the MCP server and a real Infrahub (schema change, response shape change, SDK behavior change) is detected by the integration suite before reaching a release, demonstrated within the first quarter after rollout.
- **SC-005**: After an integration test run completes or is interrupted, zero Infrahub-related Docker containers, networks, or volumes created by that run remain on the host (verified by inspection).
- **SC-006**: A new contributor following the documentation can run the integration suite successfully on their first attempt without assistance, validated by at least one external trial.

## Assumptions

- Docker (or a Docker-compatible container engine) is an acceptable prerequisite for running integration tests; contributors without it can still run unit tests.
- An official, version-pinned Infrahub container image is available and suitable for use as the system-under-test backend.
- The MCP server's existing public surface (tools, resources, prompts) is the right boundary for integration assertions; deeper white-box testing of internal modules remains the unit test suite's job.
- The CI environment used by the project supports Docker-in-Docker or an equivalent mechanism for running container-based integration tests.
- Write tools remain gated by the existing enablement flag; the integration suite will exercise at least one write tool with that flag enabled in a controlled, isolated environment.
- Existing pytest-based testing conventions (markers, fixtures, configuration) are the right vehicle for organizing and selecting the integration suite, since the unit suite already uses pytest.
- Network egress to the container image registry is available in both local-developer and CI environments at test time.
