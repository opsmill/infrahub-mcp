# Quickstart: Graph Traversal Tools

Requires a connected Infrahub server **≥ 1.10** and `infrahub-sdk >= 1.22`.

## "How are these two objects connected?"

```text
find_paths(source="InfraDevice__atl1-edge1", destination="InfraDevice__atl1-edge2")
```

Returns the shortest path(s) as ordered hops. A `count` of 0 means no path within `max_depth`. Narrow the search with `kind_filter` / `relationship_filter` / `max_depth`.

## "What's the blast radius of this object?"

```text
find_reachable(source="InfraDevice__atl1-edge1", target_kinds=["InfraCircuit", "DcimCable"])
```

Returns reachable objects of those kinds with the depth and path to each, capped at 20 by default (`max_results` to raise).

## Node references

Both tools accept either a UUID or the kind-qualified HFID that `get_nodes` already returns (e.g. `InfraDevice__atl1-edge1`). Unresolvable references return an actionable error pointing at `get_nodes` / `search_nodes`.

## Schema authoring helper

```text
get_schema(kind="InfraCircuit")            # one level of peer schema inlined (default)
get_schema(kind="InfraCircuit", expand=False)  # flat relationships only
```

Set `INFRAHUB_MCP_SCHEMA_EXPAND_PEERS=false` to disable peer inlining server-wide.

## Validation

```bash
uv sync
uv run pytest tests/unit/test_traversal.py tests/unit/test_schema_expand.py tests/unit/test_config.py -q
uv run invoke format lint
```

The unit tests run without a live server. Against a live Infrahub ≥ 1.10, exercise the two flows above.
