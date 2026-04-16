# Schema Query Depth (`INFRAHUB_MCP_MAX_QUERY_DEPTH`)

When an agent queries the schema for a kind (e.g. `InfraCircuit`), the response currently includes only the kind's own attributes and relationships. Relationships list the peer kind name but not its schema. This forces agents to make multiple round-trips to discover the full relationship chain, and means they often don't cross-reference operational state across related objects unless explicitly asked.

This design adds recursive schema expansion: when querying a kind's schema, related kinds' schemas are nested inline up to a configurable depth. This enables agents to build nested GraphQL queries that cross-reference state across related objects without hardcoding any specific schema structure.

## Configuration

**Env var:** `INFRAHUB_MCP_MAX_QUERY_DEPTH`

- Added to `ServerConfig` dataclass as `max_query_depth: int`
- Parsed via `_parse_int()` with range validation 0-5
- Default: **2**
- When set to 0: current behavior (no peer schema expansion)

The `get_schema` tool accepts an optional `depth` parameter that the agent can set per-query, capped at the server's `max_query_depth`. The `infrahub://schema/{kind}` resource always uses the server's configured value.

## Schema Helper Changes

`get_schema_detail()` in `src/infrahub_mcp/schema.py` gains two parameters:

```python
async def get_schema_detail(
    client: InfrahubClient,
    kind: str,
    branch: str | None = None,
    depth: int = 0,
    _visited: set[str] | None = None,
) -> dict[str, Any]:
```

### Depth behavior

- **depth=0** (default): Exactly current behavior. Attributes, relationships (peer name only), filters. No `peer_schema` field.
- **depth>0**: For each relationship, recursively call `get_schema_detail(peer_kind, depth=depth-1, _visited=_visited)` and attach the result as `peer_schema` on the relationship dict.

### Negative depth protection

`depth` is normalized to `max(depth, 0)` at the top of the function as a defensive measure, even though both callers (tool and resource) validate independently.

### Cycle detection

- `_visited` tracks kinds already expanded in the **current traversal path** (not globally — the same kind can appear in different branches of the tree).
- When a relationship's peer is in `_visited`, the relationship gets `"_seen": true` instead of `peer_schema`.
- The root kind is added to `_visited` before processing its relationships.

### Parallel fetching

The existing `asyncio.gather()` pattern extends naturally. At each depth level, all peer schemas for that level are fetched in parallel.

### Filter generation

Unchanged. Filters are still generated from direct peer attributes as today (depth 0 logic).

## Tool Layer (`tools/schema.py`)

`get_schema()` tool:

- New optional parameter: `depth: int | None = None`
- When `None`: uses 0 (current behavior, backward compatible)
- When provided: validated >= 0, capped at `config.max_query_depth`
- Passed through to `get_schema_detail()`
- Tool description updated to explain the depth parameter

## Resource Layer (`resources/schema.py`)

`infrahub://schema/{kind}` resource:

- Passes `depth=config.max_query_depth` to `get_schema_detail()`
- No new resource URI — the resource always provides the full picture up to the configured max
- Resource description updated to mention relationship depth

## Response Shape

At depth 2, the nested structure:

```python
{
  "kind": "InfraCircuit",
  "label": "Circuit",
  "namespace": "Infrastructure",
  "attributes": [
    {"name": "circuit_id", "kind": "Text", "optional": False},
    {"name": "status", "kind": "Text", "optional": False},
  ],
  "relationships": [
    {
      "name": "endpoints",
      "peer": "InfraInterfaceL3",
      "cardinality": "many",
      "optional": False,
      "peer_schema": {
        "kind": "InfraInterfaceL3",
        "attributes": [...],
        "relationships": [
          {
            "name": "bgp_sessions",
            "peer": "InfraBGPPeerSession",
            "cardinality": "many",
            "optional": False,
            "peer_schema": {
              "kind": "InfraBGPPeerSession",
              "attributes": [...],
              "relationships": [
                {
                  "name": "device",
                  "peer": "InfraDevice",
                  "cardinality": "one",
                  "optional": False,
                  # depth exhausted - no peer_schema
                }
              ],
              "filters": [...]
            }
          }
        ],
        "filters": [...]
      }
    },
    {
      "name": "provider",
      "peer": "InfraCircuit",
      "cardinality": "one",
      "optional": False,
      "_seen": True  # cycle detected
    }
  ],
  "filters": [...]
}
```

Rules:
- `peer_schema` only present when depth > 0 and kind not in `_visited`
- `_seen: true` only present when cycle detected (kind already in current path)
- Neither field present when depth exhausted (leaf level)
- TOON encoding applies to the top-level structure; nested `peer_schema` dicts are encoded as-is within relationship rows

## Testing

### Regression

Existing depth 0 tests must pass unchanged.

### New tests

1. **depth=1**: `peer_schema` present on relationships, contains attributes/relationships/filters of the peer kind
2. **depth=2**: Nested `peer_schema` two levels deep
3. **Cycle detection**: Kind A relates to kind B relates to kind A — `_seen: true` on the second A, no infinite recursion
4. **Self-referential**: Kind with a relationship to itself (parent/children) — `_seen: true` immediately
5. **Negative depth**: `get_schema_detail()` normalizes to 0
6. **Tool depth validation**: Negative value rejected, value > max capped
7. **Config validation**: `INFRAHUB_MCP_MAX_QUERY_DEPTH` range 0-5, invalid values rejected
8. **Resource uses config depth**: Resource passes config max to `get_schema_detail()`

## Files Changed

| File | Change |
|------|--------|
| `src/infrahub_mcp/config.py` | Add `max_query_depth` to `ServerConfig`, parse `INFRAHUB_MCP_MAX_QUERY_DEPTH` |
| `src/infrahub_mcp/schema.py` | Add `depth` + `_visited` params to `get_schema_detail()`, recursive expansion |
| `src/infrahub_mcp/tools/schema.py` | Add optional `depth` param to `get_schema()`, validation, cap at config max |
| `src/infrahub_mcp/resources/schema.py` | Pass `config.max_query_depth` to `get_schema_detail()` |
| `tests/` | New tests for depth, cycles, validation; existing tests unchanged |
