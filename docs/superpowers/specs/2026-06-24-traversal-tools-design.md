# Design: Graph traversal tools + slimmed schema expansion

- **Date:** 2026-06-24
- **Branch:** `feat/schema-query-depth`
- **Supersedes:** the recursive schema-depth expansion in PR #74 (unmerged)

## Problem

PR #74 added `INFRAHUB_MCP_MAX_QUERY_DEPTH` (0–5, default 2) so `get_schema_detail()`
recursively inlines peer schemas. It was trying to serve two distinct needs at once:

1. **Query authoring** — give an agent enough schema (kinds, attributes, relationship
   names) to hand-write a nested GraphQL query.
2. **Connection discovery / operational cross-referencing** — let an agent answer
   "what is this connected to" / "what's the blast radius".

Infrahub 1.10.0 (backend) and the Python SDK 1.22.0 added **graph path traversal**, which
serves need (2) natively and far better than dumping deep schema and hoping the agent
constructs a correct deep query: it runs server-side, is branch- and time-aware,
permission-safe, auto-excludes internal namespaces, and needs no pre-known path.

So traversal does **not** replace schema expansion — it replaces the *connection-discovery*
job. With that job moved to traversal tools, the schema feature only needs to serve query
authoring, which requires **one level** of peer expansion, not arbitrary recursion. The
recursive machinery (`@ref` dedup, per-path cycle detection, the global `_seen_kinds` set)
becomes dead weight.

## Goals

- Add two read-only MCP tools wrapping the SDK traversal API.
- Slim PR #74's schema expansion to a single level and delete the recursion machinery.
- Keep both features clearly scoped: traversal owns "what's connected / impact",
  schema expansion owns "what does the model look like so I can query it".

## Non-goals (YAGNI)

- Exposing every SDK traversal knob. We omit `excluded_namespaces`, `excluded_kinds`,
  `included_kinds`, `max_paths`, and `at` (time travel) from the tool surface initially.
  Internal namespaces are already auto-excluded server-side. These can be added later if a
  real agent workflow needs them.
- Multi-level schema expansion or any `@ref`/cycle-handling logic.
- Write/mutation behavior. Both new tools are strictly read-only.

## Versions / dependencies

- Requires **Infrahub server ≥ 1.10** and **infrahub-sdk ≥ 1.22.0**.
- Bump `pyproject.toml`: `infrahub-sdk>=1.13.5` → `infrahub-sdk>=1.22.0`.
  (`stable` is currently `>=1.20.0`; this raises it further.)

---

## Component 1 — Traversal tools (`src/infrahub_mcp/tools/traversal.py`)

New module following the existing pattern: a module-level `mcp: FastMCP = FastMCP(name="Infrahub Traversal")`,
two `@mcp.tool(..., annotations=ToolAnnotations(readOnlyHint=True))` functions tagged
`{"traversal", "retrieve"}`, mounted in `server.py` via `mcp.mount(traversal_mcp)`.

### Tool: `find_paths`

Wraps `client.traverse_paths()`. Finds the shortest path(s) between two nodes.
A result with `count == 0` is itself the "not connected" answer (no separate `path_exists`).

Parameters:

| Param | Type | Default | Notes |
|---|---|---|---|
| `source` | `str` | required | node UUID or kind-qualified HFID (see resolution) |
| `destination` | `str` | required | node UUID or kind-qualified HFID |
| `branch` | `str \| None` | `None` | defaults to default branch |
| `max_depth` | `int \| None` | `None` (SDK default 5) | max relationship hops |
| `kind_filter` | `list[str] \| None` | `None` | only traverse through these kinds |
| `relationship_filter` | `list[str] \| None` | `None` | only follow these relationship identifiers (e.g. `device__interface`) |

Returns: TOON-encoded dict (see Result shaping).

### Tool: `find_reachable`

Wraps `client.reachable_nodes()`. Impact / blast-radius analysis: which nodes of
`target_kinds` are reachable from `source`.

Parameters:

| Param | Type | Default | Notes |
|---|---|---|---|
| `source` | `str` | required | node UUID or kind-qualified HFID |
| `target_kinds` | `list[str]` | required | node kinds to search for |
| `branch` | `str \| None` | `None` | defaults to default branch |
| `max_depth` | `int \| None` | `None` (SDK default 5) | max traversal depth |
| `max_results` | `int` | `20` | distinct terminal nodes; below SDK default 50 to protect the agent context window |
| `shortest_paths_only` | `bool` | `True` | one shortest path per reachable target |

Returns: TOON-encoded dict (see Result shaping).

## Component 2 — Node resolution helper

`source`/`destination` accept a **UUID** or a **kind-qualified HFID** (the exact form
`get_nodes` already emits for relationships, e.g. `InfraDevice__atl1-edge1`).

Resolution algorithm (helper in `tools/traversal.py` or `utils.py`):

1. Try `uuid.UUID(value)`. If it parses, treat the value as a node id and pass it straight
   to the SDK (which accepts `str | InfrahubNode`).
2. Otherwise treat it as a kind-qualified HFID: split on the SDK's HFID separator
   (`__`), take the first segment as `kind` and the remainder as the `hfid` list, then
   `await client.get(kind=kind, hfid=[...], branch=branch)` and pass the resolved node.
   - *Implementation note:* confirm the separator/format against
     `InfrahubNode.get_human_friendly_id_as_string(include_kind=True)` so parsing is
     symmetric with what `get_nodes` emits.
3. On resolution failure (not found / ambiguous / malformed) raise `ToolError` via
   `_log_and_raise_error` with remediation pointing at `get_nodes` / `search_nodes` to
   obtain a valid id or HFID.

## Component 3 — Version gating

The SDK raises `VersionNotSupportedError` when these methods are called against a
pre-1.10 server. Both tools wrap the SDK call and catch it, surfacing a clear `ToolError`:
*"Graph traversal requires Infrahub ≥ 1.10."* plus the detected server version if available.

Tools always register at mount time (cheaply probing server version at startup is out of
scope); the guard is at call time.

## Component 4 — Result shaping & defaults

Encode with `toon.encode(...)` for consistency with `get_schema` / `get_nodes`.

SDK result models (for reference):

- `PathTraversalResult`: `paths: list[Path]`, `source: PathNode`, `destination: PathNode`,
  `count: int`, `excluded_kinds: list[str]`.
- `ReachableNodesResult`: `source: PathNode`, `dependencies: list[ReachableNode]`, `count: int`.
- `PathNode`: `id, kind, label, display_label, hfid` (+ `.fetch()`).
- `Path`: `hops: list[PathHop]`, `depth: int`. `PathHop`: `node: PathNode`,
  `relationship: PathRelationship | None`. `PathRelationship`: `from_rel, from_label, to_rel, to_label, kind`.
- `ReachableNode`: `node: PathNode`, `depth: int`, `path: Path`.

Shaped output (token-conscious — keep node identity compact):

```jsonc
// find_paths
{
  "source":      {"id": "...", "kind": "InfraDevice", "display_label": "atl1-edge1", "hfid": "..."},
  "destination": {"id": "...", "kind": "InfraDevice", "display_label": "atl1-edge2", "hfid": "..."},
  "count": 2,
  "paths": [
    {"depth": 3, "hops": [
      {"node": {"kind": "InfraDevice", "display_label": "atl1-edge1"}, "relationship": "interfaces"},
      {"node": {"kind": "InfraInterfaceL3", "display_label": "Ethernet1"}, "relationship": "connected_endpoint"},
      // ...
    ]}
  ]
}

// find_reachable
{
  "source": {"id": "...", "kind": "InfraDevice", "display_label": "atl1-edge1"},
  "count": 4,
  "dependencies": [
    {"depth": 2, "node": {"kind": "InfraCircuit", "display_label": "DUFF-001"},
     "path": {"depth": 2, "hops": [/* ... */]}}
  ]
}
```

Exact per-hop relationship rendering (single label vs the full `PathRelationship`) is an
implementation detail; default to the human-readable relationship label, keep node identity
to `kind` + `display_label` in hops and the full identity (`id`, `hfid`) on the top-level
`source`/`destination`/dependency node.

Defaults: `find_paths` leaves `max_depth`/`max_paths` at SDK defaults (5 / 10).
`find_reachable` uses `max_depth=5`, `max_results=20`, `shortest_paths_only=True`.

## Component 5 — Slim schema expansion (revise PR #74)

`src/infrahub_mcp/schema.py`:

- Rewrite `get_schema_detail()` to a single signature:
  `async def get_schema_detail(client, kind, branch=None, expand_peers=True) -> dict`.
- Delete `_expand_peer_schemas()` and all recursion plumbing: the `depth`, `_visited`,
  `_seen_kinds`, `_include_filters` params, the `@ref:<Kind>` back-references, and the
  per-path cycle detection.
- When `expand_peers` is `True`, each relationship gets a `peer_schema` with the peer's
  attributes and relationships **one level deep only** (peers' relationships are listed as
  plain `peer` references, not expanded). No cycle handling is needed at one level.
- Keep `_peer_rel_filters()` and the root-level `filters` map (still useful for authoring).
  Nested `peer_schema` omits `filters` (same token rationale as PR #74).

`src/infrahub_mcp/config.py`:

- Replace `max_query_depth: int` (0–5 validation) with boolean
  `schema_expand_peers: bool = True`, env var **`INFRAHUB_MCP_SCHEMA_EXPAND_PEERS`**.
- Drop the range validation that PR #74 added.

`src/infrahub_mcp/tools/schema.py`:

- `get_schema`'s `depth: int | None` param becomes `expand: bool | None` (when `None`,
  default to `config.schema_expand_peers`). Remove the negative-depth `ToolError` and the
  `min(depth, max)` capping.

`src/infrahub_mcp/resources/schema.py`:

- Use `config.schema_expand_peers` instead of the configured max depth when calling
  `get_schema_detail`.

## Component 6 — Server wiring & description

`src/infrahub_mcp/server.py`:

- `from infrahub_mcp.tools.traversal import mcp as traversal_mcp` and `mcp.mount(traversal_mcp)`.
- Add `find_paths` / `find_reachable` to the "## Available tools" description block, with a
  nudge: use these for "what's connected / impact analysis" rather than hand-built deep
  GraphQL queries.

## Testing

Follow project conventions: atomic, parametrized (no loops), imports at top, mocked SDK
client (no live server).

- `tests/unit/test_traversal.py`:
  - `find_paths` / `find_reachable` happy path → correct shaped output (mock SDK results).
  - Node resolution: UUID passthrough vs HFID → `client.get` resolution (parametrized).
  - Resolution failure → `ToolError` with remediation.
  - `VersionNotSupportedError` from the SDK → `ToolError` with the ≥1.10 message.
  - `find_reachable` default `max_results=20` is applied.
- Rework `tests/unit/test_schema_depth.py` → `test_schema_expand.py`:
  - `expand_peers=True` inlines one level of `peer_schema`; peers' relationships are not
    expanded; nested `peer_schema` has no `filters`.
  - `expand_peers=False` returns flat relationships.
  - Missing peer kind is tolerated (no crash).
- Update `tests/unit/test_config.py` for `schema_expand_peers` / `INFRAHUB_MCP_SCHEMA_EXPAND_PEERS`
  (replacing the `max_query_depth` 0–5 tests).

## Documentation

- New tool-reference page under `docs/docs/` for `find_paths` and `find_reachable`
  (Diataxis Reference), with a short usage example showing the search → traverse flow.
- Update any `get_schema` docs that mention `depth` to describe `expand`.
- `.mdx` format; run `uv run rumdl check docs/docs/` and check the docs build.

## Migration / compatibility

PR #74 is unmerged, so `INFRAHUB_MCP_MAX_QUERY_DEPTH` was never released — renaming the
config and changing the tool param are not breaking changes. No deprecation shims needed.

## Acceptance

- `uv sync && uv run pre-commit run && uv run pytest` all green.
- `find_paths` / `find_reachable` callable, return shaped TOON, resolve UUID + HFID inputs,
  and fail clearly against a pre-1.10 server.
- `get_schema` / `infrahub://schema` honor `INFRAHUB_MCP_SCHEMA_EXPAND_PEERS`; no recursion
  code remains in `schema.py`.
