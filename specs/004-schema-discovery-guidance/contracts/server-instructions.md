# Contract: Server Instructions

**Source of truth**: `build_instructions(*, read_only: bool, resources_as_tools: bool) -> str` in `src/infrahub_mcp/instructions.py`.
**Sent as**: `instructions` in `InitializeResult` (MCP 2025-11-25 and earlier) and `DiscoverResult` (MCP 2026-07-28). Also included in the `infrahub_agent` prompt.
**Limit**: under 2,000 characters in all four variants (see [research R6](../research.md#r6-content-and-size-of-the-instructions)).

The wording below is the target. Small wording changes during implementation are allowed if every rule in the "Required content" list stays true.

## Variants

| Variant | `read_only` | `resources_as_tools` |
| --- | --- | --- |
| 1 | false | false |
| 2 | false | true |
| 3 | true | false |
| 4 | true | true |

## Required content

| Rule | Read and write | Read-only | Spec |
| --- | --- | --- | --- |
| Call `get_schema()` for the kind catalog and `get_schema(kind=...)` for attributes and filter keys before querying a kind you do not know | yes | yes | FR-001 |
| Never guess kind names, attribute names or filter keys | yes | yes | FR-001 |
| Do not fetch the schema again when it is already in the conversation | yes | yes | FR-008 |
| Use `get_nodes` for nodes of one kind, including counts through `total_count`, before writing GraphQL | yes | yes | FR-001 |
| Use `find_paths` and `find_reachable` for connectivity and impact questions | yes | yes | FR-001 |
| GraphQL filters are arguments of the kind's query; there is no `filters` argument; the keys are the ones `get_schema` lists and `get_nodes` takes in `filters`; one example | yes | yes | FR-001, FR-007, FR-017 |
| How to read TOON | yes | yes | FR-001 |
| Access mode | "read and write" | "read-only" | FR-001 |
| Session-branch workflow and `propose_changes` | yes | no | FR-003 |
| Reads use the default branch unless `branch` is passed; `get_session_info` returns the session branch | yes | no | FR-001 |
| Any write tool name (`node_upsert`, `node_delete`, `mutate_graphql`, `propose_changes`, `reset_session_branch`) | allowed | forbidden | FR-003, SC-003 |
| `read_resource` line naming `infrahub://branches` and `infrahub://graphql-schema` | only when `resources_as_tools` | only when `resources_as_tools` | FR-015 |
| `read_resource` or `list_resources` when `resources_as_tools` is false | forbidden | forbidden | FR-015 |
| Text that repeats a tool description | forbidden | forbidden | FR-002 |

## Target text: variant 1 (read and write, resource tools off)

```text
Infrahub stores infrastructure data as nodes of typed kinds (for example DcimDevice), on branches.

Schema first:
- If you do not know the exact kind name, call get_schema() to list the kinds.
- If you do not know a kind's attribute, relationship or filter names, call get_schema(kind="<Kind>").
- Never guess kind names, attribute names or filter keys.
- If that schema is already in this conversation, use it and do not fetch it again.

Choosing a tool:
- Nodes of one kind, including "how many": get_nodes. Its total_count gives the count without GraphQL.
- How two nodes are connected, or what a node affects: find_paths and find_reachable, not nested GraphQL.

Filter keys (for example role__value) are the ones get_schema(kind=...) lists under "filters". In get_nodes they go in the filters argument. In GraphQL (query_graphql) they go directly on the kind's query; there is no "filters" argument. Example:
  DcimDevice(role__value: "edge") { count edges { node { id name { value } } } }

Results that contain lists use TOON: a header names the fields once, then each indented row is one record.

Access: read and write. The first write creates a session branch; the default branch is never changed directly. Read tools use the default branch unless you pass branch; to read your own changes, pass the session branch that get_session_info returns. When the changes are ready, call propose_changes to open a proposed change for human review.
```

## Read-only variants (3 and 4)

The last paragraph is replaced by:

```text
Access: read-only. This server offers no tools that change data.
```

## Resource tools variants (2 and 4)

This line is added before the "Access" paragraph:

```text
Other data: read_resource(uri="infrahub://branches") lists the branches; read_resource(uri="infrahub://graphql-schema") returns the GraphQL schema of the default branch.
```

## Tests

- All four variants contain `get_schema()`, `get_schema(kind=`, `Never guess`, `get_nodes`, `total_count`, `find_paths`, `find_reachable` and `there is no "filters" argument`.
- Variants 3 and 4 contain none of the names of the tools registered in `src/infrahub_mcp/tools/write.py`.
- Variants 2 and 4 contain `infrahub://branches` and `infrahub://graphql-schema`. Variants 1 and 3 contain neither `read_resource` nor `list_resources`.
- All four variants are under 2,000 characters.
- `mcp.instructions` equals `build_instructions(read_only=..., resources_as_tools=...)` for the server's settings, in a fresh interpreter for each variant (the pattern of `tests/unit/test_read_only_prompts.py` from PR 193).
- The `infrahub_agent` prompt output contains `build_instructions(...)` for the same settings.
