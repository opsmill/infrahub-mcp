# Feature Specification: Hash-Validated Schema Cache

**Feature Branch**: `feat/schema-cache`
**Created**: 2026-05-04
**Status**: Draft
**Input**: User description: "Hash-validated schema cache for the Infrahub MCP server: in passthrough auth modes the server builds a fresh client per request, so the SDK's per-client schema cache is discarded and every schema-touching request refetches the full schema. Introduce a process-wide schema cache validated against a cheap upstream hash endpoint, with a configurable skip-window TTL, lazy revalidation on missing kinds, and graceful degradation on transient failures."

## Clarifications

### Session 2026-05-04

- Q: Spec internally contradicted itself on whether `schema_cache_enabled` / `schema_cache_ttl` config changes apply at runtime or only after restart. Which behaviour is the requirement? → A: Restart-required; remove the runtime-toggle edge case.
- Q: Should authentication errors (4xx) during revalidation be treated the same as transient failures (serve stale + warn) or bubbled as definitive errors? → A: All upstream failures during revalidation are treated uniformly as transient — serve stale + warn.
- Q: How long may the cache serve stale data when Infrahub is sustained-down? → A: Bounded by two configurable thresholds applied together: (B) after N consecutive revalidation failures the cache is marked unsafe and reads start failing, AND (C) after an absolute ceiling on time since the last successful revalidation, the cache is marked unsafe and reads start failing. Whichever threshold trips first wins. Both thresholds are configurable; either can be disabled by setting it to zero.
- Q: What default values ship for the two circuit-break thresholds? → A: N=10 consecutive failures, T=900s (15 minutes). Both thresholds enabled by default; either can be set to 0 to disable.
- Q: Should cache counters be labelled per-branch in metrics or aggregate-only? → A: Aggregate-only at the metrics endpoint to avoid cardinality bloat from session-branch auto-creation; per-branch detail is included in WARN log lines for forensic correlation.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Fast schema reads in passthrough auth modes (Priority: P1)

An MCP-connected agent uses the server in token-passthrough or basic-passthrough authentication mode and issues several schema-reading operations in succession (catalogue, kind detail, GraphQL SDL, plus tool calls that internally consult the schema). Today each of those operations forces a full upstream schema refetch, multiplying request latency and load on Infrahub. The agent should experience the second and subsequent reads as effectively local.

**Why this priority**: This is the core problem the feature exists to solve. Without it, passthrough deployments scale poorly and burn unnecessary Infrahub server resources on identical data.

**Independent Test**: Configure the server in token-passthrough mode pointed at an Infrahub instance, issue an initial schema-reading operation (cold cache), then issue a burst of additional schema reads within the skip-window. Verify only the first request triggers an upstream schema fetch and the rest are served from cache; verify subsequent-request latency is dominated by network egress to the agent rather than upstream Infrahub round-trips.

**Acceptance Scenarios**:

1. **Given** the server is in passthrough mode and the cache is cold for branch `main`, **When** an agent reads the schema catalogue for `main`, **Then** the server fetches the full schema once, populates the cache, and returns the catalogue.
2. **Given** the cache for `main` was populated within the skip-window, **When** an agent reads the schema again for the same branch, **Then** the server returns the cached result without contacting Infrahub.
3. **Given** the cache for `main` was populated 10 minutes ago and the skip-window is 30 seconds, **When** an agent reads the schema again, **Then** the server validates currency before serving.

---

### User Story 2 - Bounded staleness when schema changes (Priority: P1)

A platform engineer updates the schema in Infrahub (adds a new kind, renames an attribute). MCP-connected agents and tools must observe the change within a bounded, predictable window — without the server requiring a restart or manual cache flush.

**Why this priority**: A cache without correctness guarantees is worse than no cache. Stale schema breaks tool calls (e.g. a write tool validating against an attribute that has been renamed). Confidence that "schema changes propagate within X seconds" is required for production use.

**Independent Test**: With the server warm-cached for branch `main`, mutate the schema in Infrahub. Wait for the configured skip-window to elapse, then issue a schema-reading operation. Verify the operation returns the new schema, and that the upstream change was detected via a cheap revalidation call rather than a full schema refetch on every request.

**Acceptance Scenarios**:

1. **Given** the cache holds schema with hash `H1` for branch `main` and the skip-window has elapsed, **When** an agent issues a schema-reading operation and the server's current hash is still `H1`, **Then** the server extends the cache, performs no full refetch, and returns the cached schema.
2. **Given** the cache holds schema with hash `H1` and the upstream hash is now `H2`, **When** an agent issues a schema-reading operation past the skip-window, **Then** the server fetches the new schema, replaces the cache entry, and returns the fresh data.
3. **Given** the cache holds schema for branch `main` and an agent requests a kind not present in the cached schema, **When** the kind is also absent upstream, **Then** the server returns a clear "kind not found" error after one revalidation; **and when** the kind exists upstream because the schema has changed since the last fetch, **Then** the server refreshes the cache and returns the kind.

---

### User Story 3 - Resilience to transient Infrahub flakes (Priority: P2)

Infrahub experiences a brief outage or network blip. The MCP server has a populated cache and is asked for schema data during the outage. The agent's request should succeed against the cached copy rather than fail wholesale.

**Why this priority**: Users expect agent workflows to tolerate transient infrastructure issues. Failing every schema-touching request because Infrahub is briefly unreachable is unacceptable when a recent cached copy is available.

**Independent Test**: Warm the cache, simulate Infrahub returning errors on revalidation calls, then issue schema reads. Verify reads succeed using cached data and that an operator-visible warning is emitted for each suppressed failure.

**Acceptance Scenarios**:

1. **Given** the cache is populated and the skip-window has elapsed, **When** the cheap hash-revalidation call fails transiently, **Then** the server logs a warning and serves cached data.
2. **Given** the cache is populated and a hash mismatch is detected, **When** the subsequent full schema refetch fails transiently, **Then** the server logs a warning and serves the previously cached data.
3. **Given** the cache is empty for the requested branch, **When** the initial schema fetch fails, **Then** the server returns the underlying error to the agent.

---

### User Story 4 - Operator visibility into cache effectiveness (Priority: P2)

A platform operator wants to know whether the cache is delivering its intended benefit and whether the schema is changing more often than expected. They look at the metrics endpoint and immediately see cache hit/miss counts, hash-match vs hash-difference counts, and revalidation-failure counts.

**Why this priority**: Without observability, "the cache works" is anecdotal. Operators need numbers to size the skip-window, diagnose flapping schemas, and verify that the feature is paying off.

**Independent Test**: Issue a known mix of cache-hit and cache-miss operations, then read the metrics endpoint. Verify the counters reflect the activity and are exposed in both Prometheus and JSON formats.

**Acceptance Scenarios**:

1. **Given** the cache is enabled and operations have run, **When** the operator queries the metrics endpoint, **Then** the response includes aggregate counters for cache hits, cache misses, hash matches, hash differences, revalidation failures, and circuit-break activations.
2. **Given** the metrics endpoint is configured for Prometheus exposition, **When** scraped, **Then** all schema-cache counters appear with stable metric names suitable for dashboarding.

---

### User Story 5 - Operator control over cache behaviour (Priority: P3)

A platform operator running the server in a development environment with frequent schema churn wants to disable the cache or shorten the skip-window. An operator running in a stable production environment wants a longer skip-window. Both should be possible through configuration without code changes.

**Why this priority**: Default behaviour fits most deployments, but operator override is a standard expectation for a feature with tunable correctness/performance trade-offs.

**Independent Test**: Configure the cache to be disabled, restart the server, and verify behaviour matches the no-cache baseline. Re-enable, set the skip-window to a non-default value, restart again, and verify it is respected. (Configuration changes take effect after restart, per the Assumptions section.)

**Acceptance Scenarios**:

1. **Given** the cache is disabled by configuration, **When** an agent issues schema reads, **Then** every request fetches schema upstream as if the cache did not exist.
2. **Given** the skip-window is configured to a non-default value, **When** the cache is consulted, **Then** the configured value governs when revalidation occurs.

---

### Edge Cases

- **Cache key collision across branches.** Two agents simultaneously work on different branches; cached entries must not bleed between them.
- **Concurrent cold-fetch.** Many agents simultaneously trigger the first read for the same branch; only one upstream fetch should occur and other requesters should wait for the same result.
- **Concurrent revalidation past skip-window.** Many agents simultaneously detect the skip-window has elapsed; only one revalidation should occur per skip-window per branch.
- **Branch deleted upstream.** The cache holds a now-obsolete entry; the server detects this on the next revalidation and removes the entry rather than retaining stale data indefinitely.
- **Non-resource consumers of schema.** Internal tool logic that consults the schema (e.g. validating a write payload against an attribute set) must benefit from the cache identically to direct schema-resource reads — the cache is not a resource-layer-only optimisation.
- **GraphQL SDL drift.** The structured schema and the GraphQL SDL are derived from the same upstream state and must invalidate together; serving a fresh structured schema with a stale SDL is a correctness defect.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST cache schema data across requests when running in token-passthrough or basic-passthrough authentication mode, so agents do not pay a full schema refetch on every operation.
- **FR-002**: System MUST scope each cache entry to a single branch, ensuring schema changes on one branch never affect cached data for another branch.
- **FR-003**: System MUST validate the freshness of cached schema data via a cheap upstream hash check once the configured skip-window has elapsed, before serving.
- **FR-004**: System MUST refresh cached schema data only when the upstream hash differs from the cached hash; matching hashes MUST extend the cache without a full refetch.
- **FR-005**: System MUST cache the GraphQL SDL alongside the structured schema and invalidate both together based on the same hash.
- **FR-006**: System MUST recover automatically when an agent requests a schema kind absent from the cached snapshot — performing a hash-validated revalidation and refetch if upstream has changed, or returning a clear "kind not found" error if the cache is current.
- **FR-007**: System MUST serialise concurrent cold fetches and concurrent revalidations so at most one upstream full-fetch occurs per branch per cache-miss event.
- **FR-008**: System MUST serve cached data and emit an operator-visible warning when *any* upstream failure occurs during revalidation or full refetch (including 4xx authentication errors, 5xx server errors, and network errors) and a previously cached entry is available; the differentiation between transient and definitive failures is not made at this layer because schema content is global per branch and serving a cached copy does not leak per-user-protected data.
- **FR-009**: System MUST surface the underlying error to the agent when no cached entry is available and the initial fetch fails.
- **FR-009a**: System MUST mark a cached entry as unsafe and switch reads to fail-closed once either of the following thresholds is crossed: (a) the count of consecutive revalidation failures for that branch reaches an operator-configurable maximum, or (b) the wall-clock time since the last successful revalidation or fetch for that branch reaches an operator-configurable absolute maximum. Whichever threshold trips first wins. Either threshold MUST be disable-able by setting its value to zero, in which case unbounded stale-serving is permitted (Option A behaviour) — operators opt in to the unbounded case explicitly.
- **FR-009b**: When a successful revalidation or refetch occurs, System MUST reset the consecutive-failure counter and the last-success timestamp for that branch's entry so the entry returns to "safe" status without restart.
- **FR-010**: System MUST evict the cache entry for a branch whose upstream existence is no longer confirmed (e.g. branch deleted upstream).
- **FR-011**: System MUST NOT duplicate caching for schema-related resources and tools that the new cache governs; pre-existing response-level caching for these specific endpoints must be removed so a single layer owns correctness.
- **FR-012**: System MUST expose aggregate counters (no per-branch labels) for cache hits, cache misses, hash matches, hash differences, revalidation failures, and circuit-break activations (entries marked unsafe by either threshold) via the existing operator-facing metrics endpoint. Per-branch detail MUST be included in the WARN log lines emitted for revalidation failures and circuit-break activations so operators can correlate metric movements with specific branches via log search.
- **FR-013**: System MUST allow operators to disable the cache through configuration; when disabled, behaviour MUST match the pre-feature baseline.
- **FR-014**: System MUST allow operators to configure the skip-window duration through the server configuration mechanism. Configuration changes take effect after a server restart (consistent with all other `ServerConfig` fields).
- **FR-014a**: System MUST allow operators to configure the consecutive-revalidation-failure ceiling (default 10) and the absolute-staleness ceiling in seconds (default 900). Either ceiling MUST be disable-able by setting its value to 0.
- **FR-015**: System MUST resolve "default branch" requests to a canonical branch name before consulting the cache, to prevent the same branch being cached under multiple keys.
- **FR-016**: System MUST NOT depend on cross-process or cross-replica state; the cache is process-local by design.
- **FR-017**: System MUST treat schema content as global per branch; cache entries MUST NOT be partitioned by user identity.

### Key Entities

- **Cached Schema Snapshot**: A point-in-time capture of a branch's schema. Carries the branch identifier, the structured schema content, the GraphQL SDL representation, the upstream-reported schema hash at fetch time, the wall-clock time of the last successful fetch or revalidation, and the count of consecutive revalidation failures since the last success.
- **Schema Hash**: A short upstream-supplied identifier that changes if and only if the schema content for a branch changes. Used as the equality test for "is my cached snapshot still current?"
- **Skip-Window**: The configurable duration after a fetch during which the cache is trusted without revalidation. Outside the window, every read triggers a hash check.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: With the cache enabled and the skip-window respected, repeat schema reads against the same branch incur no upstream schema-body transfer for the duration of the skip-window.
- **SC-002**: After an upstream schema change, all subsequent reads reflect the change within the skip-window plus one round-trip to the cheap hash-revalidation endpoint.
- **SC-003**: A burst of 10 simultaneous schema reads against a cold cache for the same branch results in exactly one upstream full schema fetch.
- **SC-004**: In steady state with no schema changes, the cache-hit ratio reported by the metrics endpoint exceeds 90 % under realistic agent workloads.
- **SC-005**: A transient upstream failure of the revalidation call does not produce user-visible errors when a cached entry exists and neither circuit-break threshold has been crossed; the failure is observable as a counter increment and a log warning.
- **SC-005a**: When the configured consecutive-failure or absolute-staleness threshold is crossed, the cache stops serving the affected branch's entry and subsequent reads return a clear "schema unavailable" error to the agent; the threshold crossing is observable via metrics so operators can correlate it with the upstream outage.
- **SC-006**: Schema reads in passthrough authentication modes complete with measurably lower median latency than the pre-feature baseline (specifically, no upstream schema fetch on cache-hit paths) on identical workloads.
- **SC-007**: Operators can verify cache effectiveness without reading source code, by inspecting only the metrics endpoint.

## Assumptions

- Schema content is identical for any authenticated user on a given branch; per-user content filtering applies only to node data, not to schema definitions. Cache entries can therefore be shared across users without information leakage.
- The Infrahub server exposes a cheap "hash only" endpoint (existing `GET /api/schema/summary`) that returns a small response containing the current schema hash without the full schema body.
- The MCP server runs as a single process; multi-replica deployments are out of scope for this feature and may be addressed separately.
- The MCP server does not expose schema-mutation tools; the schema only ever changes from outside this server's request flow, so write-through invalidation is unnecessary.
- Schema mutations in production are infrequent (minutes-to-hours scale, not seconds); a default skip-window of approximately 30 seconds is acceptable for the typical deployment.
- The existing operator-facing metrics endpoint is the canonical surface for cache observability; no new operator UI is required.
- Configuration changes affecting the cache (enable/disable, skip-window) are applied through the existing server configuration mechanism and may take effect after a server restart.
- The number of distinct branches in active use against a single MCP server is bounded enough that an in-memory dictionary with no eviction is acceptable for the foreseeable future.
