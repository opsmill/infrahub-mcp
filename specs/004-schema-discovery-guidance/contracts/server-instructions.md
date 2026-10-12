# Contract: Server Instructions

**Source of truth**: `build_instructions(*, read_only: bool) -> str` in `src/infrahub_mcp/instructions.py`.
**Sent as**: `instructions` in `InitializeResult` (MCP 2025-11-25 and earlier) and `DiscoverResult` (MCP 2026-07-28). Also included in the `infrahub_agent` prompt.
**Limit**: under 2,000 characters in both modes (see [research R6](../research.md#r6-content-and-size-of-the-instructions)).

The wording below is the target. Small wording changes during implementation are allowed if every rule in the "Required content" list stays true.

## Required content

| Rule | Read and write | Read-only | Spec |
| --- | --- | --- | --- |
| Call `get_schema()` for the kind catalog and `get_schema(kind=...)` for attributes and filter keys before querying a kind you do not know | yes | yes | FR-001 |
| Never guess kind names, attribute names or filter keys | yes | yes | FR-001 |
| Do not fetch the schema again when it is already in the conversation | yes | yes | FR-008 |
| GraphQL filters are arguments of the kind's query; there is no `filters` argument; one example | yes | yes | FR-001, FR-007 |
| How to read TOON | yes | yes | FR-001 |
| Access mode | "read and write" | "read-only" | FR-001 |
| Session-branch workflow and `propose_changes` | yes | no | FR-003 |
| Any write tool name (`node_upsert`, `node_delete`, `mutate_graphql`, `propose_changes`, `reset_session_branch`) | allowed | forbidden | FR-003, SC-003 |
| Text that repeats a tool description | forbidden | forbidden | FR-002 |

## Target text: read and write

```text
Infrahub stores infrastructure data as nodes of typed kinds (for example DcimDevice), on branches.

Schema first:
- If you do not know the exact kind name, call get_schema() to list the kinds.
- If you do not know a kind's attribute, relationship or filter names, call get_schema(kind="<Kind>").
- Never guess kind names, attribute names or filter keys.
- If that schema is already in this conversation, use it and do not fetch it again.

GraphQL (query_graphql): the query for a kind has the kind's name, and filters are arguments of that query. There is no "filters" argument. Example:
  DcimDevice(role__value: "edge") { count edges { node { id name { value } } } }

Results that contain lists use TOON: a header names the fields once, then each indented row is one record.

Access: read and write. The first write creates a session branch; the default branch is never changed directly. When the changes are ready, call propose_changes to open a proposed change for human review.
```

## Target text: read-only

Same as above, with the last paragraph replaced by:

```text
Access: read-only. This server offers no tools that change data.
```

## Tests

- Both texts contain `get_schema()`, `get_schema(kind=`, `Never guess` and `There is no "filters" argument`.
- The read-only text contains none of the names of the tools registered in `src/infrahub_mcp/tools/write.py`.
- Both texts are under 2,000 characters.
- `mcp.instructions` equals `build_instructions(read_only=_config.read_only)`, in a fresh interpreter for each mode (the pattern of `tests/unit/test_read_only_prompts.py` from PR 193).
- The `infrahub_agent` prompt output contains `build_instructions(...)` for the same mode.
