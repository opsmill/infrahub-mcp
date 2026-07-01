# Feature Specification: Graph Traversal Tools + Single-Level Schema Expansion

**Feature Branch**: `feat/schema-query-depth` (speckit feature `002-traversal-tools`)
**Created**: 2026-06-24
**Status**: Draft
**Input**: User description: "Replace/improve the schema query-depth idea using Infrahub 1.10's transversal (graph traversal) query. Add traversal MCP tools and slim schema expansion to a single level."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Discover how two objects are connected (Priority: P1)

An AI assistant is asked "how is device `atl1-edge1` connected to device `atl1-edge2`?". Today it must guess the relationship path and hand-build a deep, fragile nested GraphQL query — often wrong, often expensive. With this feature it calls a single tool with the two objects and gets back the actual shortest path(s) through the live data graph.

**Why this priority**: This is the headline capability the feature exists for, and the one the old schema-depth approach served worst. It is independently valuable on its own.

**Independent Test**: Provide two connected objects and confirm the tool returns one or more paths with ordered hops; provide two unconnected objects and confirm it returns a zero-count result rather than an error.

**Acceptance Scenarios**:

1. **Given** two objects with a relationship path between them, **When** the agent requests paths between them, **Then** the response lists the shortest path(s) as ordered hops naming each intermediate object and the relationship used.
2. **Given** two objects with no path within the search limit, **When** the agent requests paths, **Then** the response indicates zero paths (not an error).
3. **Given** an object referenced by its human-friendly name rather than its internal id, **When** the agent requests paths, **Then** the reference is resolved automatically and the traversal proceeds.

---

### User Story 2 - Find the blast radius of an object (Priority: P2)

An AI assistant is asked "what circuits and cables are affected if `atl1-edge1` goes down?". It calls a single tool naming the source object and the kinds of interest, and gets back every reachable object of those kinds, each with the path that reaches it.

**Why this priority**: Impact/dependency analysis is the second high-value traversal use case, distinct from point-to-point pathing. Valuable independently of US1.

**Independent Test**: Provide a source object and a list of target kinds; confirm the response lists reachable objects of those kinds with their depth and path, capped at a sane default.

**Acceptance Scenarios**:

1. **Given** a source object connected to objects of the requested kinds, **When** the agent requests reachable nodes, **Then** the response lists those objects with the depth and path to each.
2. **Given** a request that would match a very large number of objects, **When** the agent requests reachable nodes without overrides, **Then** the result is capped at a conservative default count to protect the agent's context budget.

---

### User Story 3 - Get just-enough schema to author a query (Priority: P3)

An AI assistant requesting a kind's schema sees that kind's attributes and relationships **plus one level** of each related peer's attributes and relationships — enough to author a nested query in one shot — without an unbounded, token-heavy recursive dump. An operator can disable peer inlining entirely via a single setting.

**Why this priority**: Schema context is still needed for query authoring, but the deep-recursion machinery is no longer justified now that connection discovery is served by US1/US2. This story replaces that machinery with a simpler, controllable one level.

**Independent Test**: Request a kind's schema with peer expansion on and confirm exactly one level of peer schema is inlined (peers' own relationships are not expanded); request with expansion off and confirm relationships are flat references.

**Acceptance Scenarios**:

1. **Given** peer expansion enabled, **When** the agent requests a kind's schema, **Then** each relationship includes the peer's attributes and relationships, inlined a single level deep, and the peer block carries no filters.
2. **Given** peer expansion disabled by configuration, **When** the agent requests a kind's schema, **Then** relationships are returned as plain peer references with no inlined schema.
3. **Given** a relationship pointing at a kind that does not exist, **When** the schema is requested with expansion on, **Then** the relationship is still returned without inlined schema and no error is raised.

### Edge Cases

- A node reference that is neither a valid id nor a resolvable name → the tool returns a clear, actionable error pointing the agent at the node-listing tools.
- The connected Infrahub server is older than the version that supports graph traversal → the tool returns a clear "not supported on this server version" error rather than a raw failure.
- A reachable-nodes query matches more objects than the default cap → results are limited and the agent can raise the cap explicitly.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST expose a read-only tool that returns the shortest path(s) between two objects, with each path expressed as ordered hops (object identity + relationship used).
- **FR-002**: System MUST expose a read-only tool that returns objects of caller-specified kinds reachable from a source object, each with its depth and path.
- **FR-003**: Both tools MUST accept an object reference as either an internal id or a human-friendly, kind-qualified name, resolving the latter automatically.
- **FR-004**: Both tools MUST allow scoping the search (at minimum: maximum depth; for pathing also which kinds and relationships to traverse; for reachability also a result cap and shortest-paths-only toggle), with conservative defaults.
- **FR-005**: When the connected server does not support graph traversal, both tools MUST fail with a clear, actionable message naming the required server version.
- **FR-006**: When an object reference cannot be resolved, the tools MUST fail with a clear message directing the caller to the node-listing tools.
- **FR-007**: Tool responses MUST be encoded in the project's compact response format and keep per-hop content minimal to limit token usage.
- **FR-008**: The schema-detail capability MUST inline at most one level of related peer schemas; it MUST NOT recurse further, deduplicate via back-references, or perform cycle detection.
- **FR-009**: Inlined peer schemas MUST omit the filter map; the root schema MUST retain its full filter map (including peer-derived filters).
- **FR-010**: Peer inlining MUST be controllable by a single boolean server setting (default on) and overridable per schema-tool call.
- **FR-011**: Both new tools MUST be read-only and MUST NOT be tagged as write tools.

### Key Entities *(include if feature involves data)*

- **Path**: An ordered route between two objects, made of hops; carries a depth.
- **Hop**: One step in a path — the object reached and the relationship used to reach it.
- **Object identity**: The lightweight identity of an object surfaced in results (id, kind, display label, human-friendly id).
- **Reachable object**: An object reachable from a source — its identity, its depth, and the path to it.
- **Peer schema (one level)**: A related kind's attributes and relationships, inlined under a relationship without further expansion or filters.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An agent can determine whether and how two objects are connected with a single tool call, replacing what previously required schema inspection plus a hand-built multi-hop query.
- **SC-002**: An agent can enumerate the impacted objects of given kinds from a source with a single tool call, with results capped by default to a small, bounded number.
- **SC-003**: A schema-detail response inlines exactly one level of peer schema (zero deeper), measurably reducing response size versus the previous default two-level recursion.
- **SC-004**: Against an unsupported server, both tools return an actionable error 100% of the time instead of an unhandled failure.
- **SC-005**: All new behavior is covered by tests that run without a live server, and the existing test suite continues to pass.

## Assumptions

- The connected Infrahub server is version 1.10 or later for the traversal tools to function; older servers are handled with a clear error, not a crash.
- Agents obtain object ids or kind-qualified human-friendly names from the existing node-listing tools, so those are acceptable inputs.
- The previous `INFRAHUB_MCP_MAX_QUERY_DEPTH` setting was never released (it lives only on an unmerged branch), so replacing it with a boolean toggle is not a breaking change.
- Connection discovery is better served by graph traversal than by deep schema inlining, so schema expansion is intentionally reduced to one level.
