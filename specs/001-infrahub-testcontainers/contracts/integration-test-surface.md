# Contract: MCP Surface Covered by Integration Tests (v1)

**Feature**: 001-infrahub-testcontainers
**Date**: 2026-05-22

The Infrahub MCP server is itself the public contract. This document is not a new API — it is the **subset of the existing MCP server surface that the v1 integration suite asserts against**. Anything outside this list is covered by the unit suite only.

Each item below lists: the MCP entity, the assertion shape, and which spec FR it backs.

**Drive layer (clarified 2026-06-15)**: all assertions are made through the in-process FastMCP `Client` (in-memory transport) against the `mcp` server instance. The Starlette ASGI auth/OIDC/transport layer is bypassed; FastMCP-level middleware (`ReadOnlyMiddleware`, audit, caching, error handling) still runs — so the `read_only` write-gating contract (T4) and MCP-standard error masking (T3, F1) hold under this harness.

---

## R1. Schema resource (`schema://`)

**MCP entity**: Resource — schema introspection.

**Test contract**:

- GIVEN the session-scoped seeded schema
- WHEN the test reads the `schema` resource via the MCP client
- THEN the response includes every kind declared in `tests/integration/fixtures/schema_minimal.yml`
- AND the response shape conforms to `SchemaResource` Pydantic model

**Backs**: FR-005 (schema resource), FR-012 (clear failure message).

---

## R2. Branches resource (`branches://`)

**MCP entity**: Resource — branch listing.

**Test contract**:

- GIVEN a per-test branch has been created
- WHEN the test reads the `branches` resource via the MCP client
- THEN the response includes both `main` and the per-test branch name
- AND `main` is flagged as the default branch

**Backs**: FR-005 (branch listing).

---

## T1. `get_node` tool

**MCP entity**: Tool (read).

**Test contract** (per parametrized case):

- GIVEN seeded baseline nodes on `main`
- WHEN the test calls `get_node(kind=..., id=...)`
- THEN the response includes the requested attributes and matches the seeded value
- AND the response is deterministic across repeated calls

**Backs**: FR-005 (node read tools).

---

## T2. `get_nodes` tool

**MCP entity**: Tool (read).

**Test contract** (at least 2 parametrized cases):

1. **Filter**: GIVEN seeded nodes, WHEN `get_nodes(kind=..., filters={...})` is called, THEN only matching nodes are returned.
2. **Pagination**: GIVEN ≥ N+1 seeded nodes of a kind, WHEN `get_nodes(kind=..., limit=N)` is called, THEN exactly N are returned AND a paging cursor (or equivalent) lets the next page be requested.

**Backs**: FR-005 (node read tools), `get_nodes` pagination unit test parity (`tests/unit/test_get_nodes_pagination.py`).

---

## T3. `graphql_query` tool

**MCP entity**: Tool (read).

**Test contract**:

- GIVEN a known seeded graph
- WHEN the test calls `graphql_query(query=..., variables=...)` with a query against the seeded shape
- THEN the response matches the expected shape
- AND query errors (e.g., unknown field) surface as MCP-standard errors, not internal stack traces (Principle VI)

**Backs**: FR-005 (GraphQL tool), Constitution Principle I and VI.

---

## T4. One representative write tool (e.g., `create_node`)

**MCP entity**: Tool (write — tagged `"write"`).

**Test contract**:

- GIVEN a per-test branch and `read_only=false`
- WHEN the test calls the write tool with valid input
- THEN a new node exists on the per-test branch
- AND the node does NOT appear on `main` (verifies Principle III: branch isolation)
- AND when the per-test branch is deleted, the node disappears (verifies cleanup)

Additionally:

- GIVEN `read_only=true` (separate test class with reconfigured `McpServerUnderTest`)
- WHEN the test calls the write tool
- THEN the call is rejected with an MCP-standard error
- AND no node is created on any branch

**Backs**: FR-005 (write tool), Constitution Principles III and VI.

---

## V1. Infrahub version-compatibility check (FR-013)

**MCP entity**: N/A — a backend version probe via the SDK (not an MCP tool/resource).

**Test contract**:

- GIVEN the running session Infrahub container
- WHEN the version-compat test reads the running Infrahub version and compares it to the pinned / SDK-supported range
- THEN a matching version passes
- AND a mismatch produces a distinct, clearly-labeled result (an `xfail`/`skip` whose reason names both versions, or a "version drift"-labeled failure) — never an ordinary functional-assertion failure

**Backs**: FR-013, "Infrahub version drift" edge case.

---

## Failure-mode contracts (cross-cutting)

These assertions are not tied to a specific tool/resource; they apply to every integration test.

- **F1**: When the Infrahub container is not reachable (simulated by tearing it down mid-suite), MCP calls return an MCP-standard error with no internal stack trace exposed.
- **F2**: When a tool is called with malformed input, the MCP layer rejects it via FastMCP's schema enforcement before any Infrahub call is made (assertable by checking no SDK call was issued — uses a spy on the SDK client).

---

## Explicit non-contract

The following are **NOT** asserted in v1 (covered by unit suite or deferred):

- Prompt templates (rendering, parameter substitution).
- OpenTelemetry trace emission shape.
- Prometheus metrics shape.
- Rate limiting middleware behavior under load.
- Response caching middleware TTL semantics.
- Audit middleware output format.
- OIDC token validation flow (unit-tested with mocked IdP).
- Token-passthrough flow (unit-tested in `tests/unit/test_token_passthrough.py`).

Any of these may be added in a future increment without changing this v1 contract.
