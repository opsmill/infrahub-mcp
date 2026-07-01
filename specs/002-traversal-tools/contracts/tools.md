# Tool Contracts

## `find_paths` (read-only)

Find the shortest path(s) between two objects.

**Inputs**

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `source` | string | yes | — | UUID or kind-qualified HFID (e.g. `InfraDevice__atl1-edge1`) |
| `destination` | string | yes | — | UUID or kind-qualified HFID |
| `branch` | string | no | default branch | Branch to query |
| `max_depth` | integer | no | SDK default (5) | Max relationship hops |
| `kind_filter` | list[string] | no | none | Only traverse through these kinds |
| `relationship_filter` | list[string] | no | none | Only follow these schema relationship identifiers |

**Output**: TOON-encoded dict — `source`, `destination`, `count`, `paths[]` (see data-model). `count == 0` ⇒ no path.

**Errors**: `ToolError` on unresolvable node reference (remediation → node-listing tools); `ToolError` on pre-1.10 server (remediation → required version).

## `find_reachable` (read-only)

Find objects of given kinds reachable from a source object (impact analysis).

**Inputs**

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `source` | string | yes | — | UUID or kind-qualified HFID |
| `target_kinds` | list[string] | yes | — | Kinds to search for |
| `branch` | string | no | default branch | Branch to query |
| `max_depth` | integer | no | SDK default (5) | Max traversal depth |
| `max_results` | integer | no | 20 | Max distinct reachable nodes |
| `shortest_paths_only` | boolean | no | true | One shortest path per target |

**Output**: TOON-encoded dict — `source`, `count`, `dependencies[]` (each `{depth, node, path}`).

**Errors**: same as `find_paths`.

## `get_schema` (modified, read-only)

The `depth: int` parameter is replaced by `expand: bool | None`.

| Param | Type | Required | Default | Description |
|---|---|---|---|---|
| `kind` | string | no | none (lists catalog) | Kind to detail |
| `branch` | string | no | default branch | Branch to query |
| `expand` | boolean | no | server `INFRAHUB_MCP_SCHEMA_EXPAND_PEERS` (default true) | Inline one level of peer schema |

**Output**: unchanged shape except peer expansion is single-level (see data-model). The `infrahub://schema/{kind}` resource honors the server toggle.

## Configuration contract

| Env var | Type | Default | Effect |
|---|---|---|---|
| `INFRAHUB_MCP_SCHEMA_EXPAND_PEERS` | boolean (`true/false/1/0/yes/no`) | `true` | Whether schema detail inlines one level of peer schema |

Replaces the unreleased `INFRAHUB_MCP_MAX_QUERY_DEPTH`.
