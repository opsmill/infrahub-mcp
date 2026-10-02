# Research: Graph Traversal Tools + Single-Level Schema Expansion

## Decision 1 — Use Infrahub graph traversal for connection discovery

**Decision**: Wrap the SDK's `traverse_paths` / `reachable_nodes` (Infrahub 1.10 `InfrahubPathTraversal` / `InfrahubReachableNodes`) as MCP tools, instead of expanding deep schema so the agent can hand-build nested queries.

**Rationale**: Traversal runs server-side over the live data graph: branch- and time-aware, permission-safe, internal namespaces auto-excluded, no pre-known path required. It directly answers "how are these connected?" and "what's reachable?", which deep schema inlining served poorly (the agent had to guess the path and could build wrong/expensive queries).

**Alternatives rejected**:
- *Recursive schema-depth inlining (the prior PR74 approach)*: gives the model the model, not the data; it cannot tell the agent what is actually connected, only what could be. Retained only as a one-level query-authoring aid (Decision 5).
- *Exposing `path_exists` as a third tool*: redundant — a `find_paths` result with `count == 0` answers existence.

## Decision 2 — SDK floor `infrahub-sdk >= 1.22.0`

**Decision**: Raise the dependency floor from the branch's `>=1.13.5` to `>=1.22.0`.

**Rationale**: The traversal client methods and result models (`infrahub_sdk.graph_traversal`) landed in SDK 1.22.0. `stable` already pins `>=1.20.0`; 1.22 is the minimum that exposes the API.

## Decision 3 — Accept UUID or kind-qualified HFID for node references

**Decision**: `source`/`destination`/`source` accept either a node UUID or a kind-qualified HFID (e.g. `InfraDevice__atl1-edge1`). UUIDs pass straight to the SDK; HFIDs are parsed (`Kind__part1__part2`, separator `__`) and resolved via `client.get(kind=, hfid=, branch=)`.

**Rationale**: The SDK accepts only a UUID string (or an `InfrahubNode`), but an agent's natural handle is the human-friendly name the existing `get_nodes` tool already emits (`get_human_friendly_id_as_string(include_kind=True)`). Auto-resolving keeps the tools usable without a mandatory id-lookup round-trip. Resolution failure raises a domain error translated to an actionable `ToolError`.

**Alternatives rejected**: UUID-only (forces a two-step flow); kind+filter dict (more verbose, adds 0/many-match ambiguity handling).

## Decision 4 — Version gating at call time

**Decision**: Let the SDK's `VersionNotSupportedError` propagate from the core, and translate it to a `ToolError` in the tool wrapper ("requires Infrahub 1.10 or later"). Tools always register; the guard fires on call.

**Rationale**: Probing server version at mount time is not cheap or reliable; the SDK already raises a precise error against pre-1.10 servers. Translating it preserves the project's remediation-hint error pattern.

## Decision 5 — Single-level schema expansion via boolean toggle

**Decision**: `get_schema_detail(client, kind, branch=None, expand_peers=True)` inlines exactly one level of peer schema (peers' relationships stay flat, peer block omits filters). Delete the recursion, `@ref` dedup, cycle detection, and `_seen_kinds`. Replace `INFRAHUB_MCP_MAX_QUERY_DEPTH` (int 0–5) with boolean `INFRAHUB_MCP_SCHEMA_EXPAND_PEERS` (default true).

**Rationale**: With connection discovery moved to traversal, the only remaining job of schema inlining is query authoring, which needs one level (immediate peers + their attributes). One level has no cycles or cross-branch repeats, so the recursion/dedup/cycle machinery (~150 lines) is dead weight. PR74 is unmerged, so the rename is non-breaking.

## Decision 6 — Conservative, token-aware result shaping

**Decision**: Encode results in TOON. Keep per-hop content minimal (`kind` + `display_label` per hop node, relationship name). Surface full identity (`id`, `hfid`) only on top-level source/destination/dependency nodes. Default `find_reachable` `max_results` to 20 (below the SDK's 50) to protect the agent context window; leave `find_paths` at SDK defaults (depth 5, 10 paths).

**Rationale**: Traversal results can be large; agents pay per token. Minimal hop content plus a low default cap keeps responses cheap while remaining overridable.

## Decision 7 — Testability without a live server

**Decision**: Put resolution, shaping, and orchestration in `traversal.py` (plain functions taking `client`), unit-tested with mocked SDK clients and real SDK result models. Tool wrappers delegate to testable `_find_*_impl(ctx, ...)` functions exercised with a mock context.

**Rationale**: The existing `test_tools.py` runs against a live Infrahub (CI only); the new logic must be verifiable offline, matching the pattern used by `test_schema_depth.py`/`test_config.py`. Live traversal data is not guaranteed in the demo dataset, so no new live tests are added.
