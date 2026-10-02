# Data Model: Graph Traversal Tools + Single-Level Schema Expansion

These entities are not persisted — they are the shapes of SDK results and the compact dicts the tools return. SDK source models live in `infrahub_sdk.graph_traversal`.

## SDK result models (inputs to shaping)

| Model | Fields | Notes |
|---|---|---|
| `PathNode` | `id: str`, `kind: str`, `label: str`, `display_label: str`, `hfid: list[str]` | Lightweight identity; `.fetch()` resolves the full node |
| `PathRelationship` | `from_rel, from_label, to_rel, to_label, kind` | The edge traversed; `from_label` is the relationship name as seen from the previous node |
| `PathHop` | `node: PathNode`, `relationship: PathRelationship \| None` | `relationship` is `None` for the source-anchored first hop |
| `Path` | `hops: list[PathHop]`, `depth: int` | One route between two nodes |
| `PathTraversalResult` | `paths: list[Path]`, `source: PathNode`, `destination: PathNode`, `count: int`, `excluded_kinds: list[str]` | Result of `traverse_paths` |
| `ReachableNode` | `node: PathNode`, `depth: int`, `path: Path` | A reachable target plus the route to it |
| `ReachableNodesResult` | `source: PathNode`, `dependencies: list[ReachableNode]`, `count: int` | Result of `reachable_nodes` |

## Tool output shapes (after shaping → TOON)

### `find_paths` output

```jsonc
{
  "source":      {"id": "...", "kind": "InfraDevice", "display_label": "atl1-edge1", "hfid": ["atl1-edge1"]},
  "destination": {"id": "...", "kind": "InfraDevice", "display_label": "atl1-edge2", "hfid": ["atl1-edge2"]},
  "count": 2,
  "paths": [
    {"depth": 3, "hops": [
      {"node": {"kind": "InfraDevice", "display_label": "atl1-edge1"}},
      {"node": {"kind": "InfraInterfaceL3", "display_label": "Ethernet1"}, "relationship": "interfaces"}
    ]}
  ]
}
```

### `find_reachable` output

```jsonc
{
  "source": {"id": "...", "kind": "InfraDevice", "display_label": "atl1-edge1", "hfid": ["atl1-edge1"]},
  "count": 4,
  "dependencies": [
    {"depth": 2, "node": {"id": "...", "kind": "InfraCircuit", "display_label": "DUFF-001", "hfid": ["DUFF-001"]},
     "path": {"depth": 2, "hops": [/* ... */]}}
  ]
}
```

**Shaping rules**:
- Top-level `source` / `destination` / dependency `node`: full identity (`id`, `kind`, `display_label`, `hfid`).
- Per-hop `node`: compact (`kind`, `display_label` only).
- Per-hop `relationship`: the `from_label` string; omitted on the first (source-anchored) hop.

## Schema-detail entity (single-level peer expansion)

`get_schema_detail` returns:

| Key | Shape |
|---|---|
| `kind`, `label`, `namespace` | scalars |
| `attributes` | list of `{name, kind, optional}` |
| `relationships` | list of `{name, peer, cardinality, optional}`, each optionally with `peer_schema` |
| `filters` | list of `{filter, type}` (root only; includes peer-derived filters) |
| `relationships[].peer_schema` | `{kind, label, namespace, attributes, relationships}` — one level, **no** `filters`, peers' relationships are plain references (no nested `peer_schema`) |

`peer_schema` is present only when `expand_peers` is true and the peer kind exists.
