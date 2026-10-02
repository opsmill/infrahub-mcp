# 8. Graph Traversal Tools over Recursive Schema-Depth Expansion

**Status:** Accepted
**Date:** 2026-06-24
**Author:** @bkohler

## Context

Agents need to answer two different questions about Infrahub data:

1. *What does the model look like?* — enough schema (kinds, attributes,
   relationship names) to author a nested GraphQL query.
2. *How are things actually connected?* — the live data relationships
   between specific objects ("how is device A connected to device B?",
   "what is the blast radius of object X?").

An earlier proposal (the unreleased `INFRAHUB_MCP_MAX_QUERY_DEPTH` work)
tried to serve **both** with one mechanism: recursively inlining peer
schemas several levels deep so an agent could see the whole schema graph
and hand-build a deep query. That conflation had real costs — large,
token-heavy responses requiring `@ref` deduplication and per-path cycle
detection, and it still only described what *could* connect, never what
*does*. Agents had to guess relationship paths and frequently built
wrong or expensive nested queries.

Infrahub 1.10 (backend) and infrahub-sdk 1.22 added **graph path
traversal** (`traverse_paths`, `reachable_nodes`): server-side,
branch- and time-aware, permission-safe walks of the live data graph.

## Decision

Split the two concerns and serve each with the right tool:

- **Connection discovery** → two read-only MCP tools, `find_paths` and
  `find_reachable`, wrapping the SDK traversal API. They accept a node
  UUID or a kind-qualified HFID, fail clearly against pre-1.10 servers,
  and return compact, TOON-encoded results.
- **Query authoring** → `get_schema` / the `infrahub://schema` resource
  inline at most **one** level of peer schema, gated by the boolean
  `INFRAHUB_MCP_SCHEMA_EXPAND_PEERS` setting. The recursive expansion,
  `@ref` deduplication, and cycle detection are removed.

Traversal logic lives in `traversal.py` (unit-testable without a live
server); thin wrappers in `tools/traversal.py` translate SDK errors to
`ToolError`, mirroring the existing `schema.py` ↔ `tools/schema.py` split.

## Consequences

- Connection/impact questions are answered in one server-side call
  instead of schema inspection plus a hand-built multi-hop query.
- Schema responses are smaller and the schema helper is simpler
  (~150 lines of recursion/dedup/cycle machinery removed).
- The traversal tools require Infrahub ≥ 1.10 and infrahub-sdk ≥ 1.22;
  older servers receive an actionable error rather than a crash.
- `INFRAHUB_MCP_MAX_QUERY_DEPTH` is replaced by
  `INFRAHUB_MCP_SCHEMA_EXPAND_PEERS`; since the former was never
  released, this is not a breaking change.

## Alternatives Considered

- **Keep recursive schema depth, skip traversal tools.** Rejected: it
  never answers the data-connection question and keeps the costly
  recursion machinery.
- **Expose the SDK's `path_exists` as a third tool.** Rejected as
  redundant — a `find_paths` result with `count == 0` answers existence.
- **Resolve only UUIDs (no HFID).** Rejected: agents naturally hold the
  kind-qualified HFID that `get_nodes` already emits; requiring a UUID
  forces an extra lookup round-trip.
