# Contracts: MCP Tool Interfaces

The server's external interface is its MCP tools. This feature adds one tool and adjusts the behavioral contract of three existing entry points. Tool I/O is enforced by FastMCP schema generation from the Python signatures.

## NEW tool: `reset_session_branch`

- **Tags**: `{"session", "write"}` · **Annotations**: `readOnlyHint=False`, `idempotentHint=False`, `destructiveHint=False`
- **Availability**: only when `read_only=false` (mounted in `write_mcp`; blocked by `ReadOnlyMiddleware` otherwise).

**Input**
| Param | Type | Default | Meaning |
|---|---|---|---|
| `branch` | `str \| None` | `None` | Omit → drop this session's cached branch (next write provisions a fresh one). Provide → switch this session to the named branch. |

**Output** (`dict[str, Any]`)
```jsonc
{
  "session_branch": "mcp/session-20260604-ab12cd34",  // active branch after the call, or null when reset-to-empty
  "previous_branch": "mcp/session-20260603-deadbeef",  // what it was before, or null
  "created": false,                                     // true when a new branch was provisioned by this call
  "action": "reset" | "switched" | "created"           // what happened
}
```

**Behavior / errors**
| Case | Result |
|---|---|
| `branch=None` | clear this session's entry; `action="reset"`, `session_branch=null` |
| `branch` exists, writable, non-default | switch session to it; `action="switched"` |
| `branch` does not exist, **conforms** to `branch_pattern` | create it, switch session to it, inform caller; `action="created"`, `created=true` |
| `branch` does not exist, **non-conformant** | `ToolError` — name does not match the configured convention; nothing created |
| `branch` == instance default branch | `ToolError` (reuse `assert_writable_branch` message) |
| `branch` exists but `status ∈ {MERGED, DELETING}` | `ToolError` — cannot target a read-only/merged branch |
| isolation | only the calling session's entry changes; other sessions unaffected |

## MODIFIED behavior: `get_or_create_session_branch` (internal, backs all write tools)

- Returns `str` (unchanged signature). Now keyed by the per-session object (`_session_obj(ctx)`).
- On a cached entry, validates via `client.branch.get()`:
  - `BranchNotFoundError` → clear + recreate + `ctx.warning` naming old branch (existing).
  - `status ∈ {MERGED, DELETING}` → clear + recreate + `ctx.warning` naming **old and new** branch (NEW — satisfies FR-002/FR-004/SC-005).
  - writable → reuse.
- Concurrency: serialized per session via that session's lock; concurrent writes in one session converge on one branch (FR-008).

## MODIFIED output: `get_session_info`

- `session_branch` / `has_session_branch` now reflect **the calling session's** branch (via `get_session_branch(ctx)`), not a process-global value. Output shape unchanged (backward compatible).

## MODIFIED behavior: `propose_changes`

- Reads the **calling session's** branch via `get_session_branch(ctx)`. Same "no active session branch" error when the session has none. No signature/output change.

## MODIFIED behavior: `mutate_graphql`

- The explicit `branch` parameter is **removed** — like `node_upsert`/`node_delete`, the mutation always targets the active session branch (switch deliberately via `reset_session_branch`). Branch-management (`Branch*`) and schema (`Schema*`) mutations, and non-mutation operations, are rejected so writes cannot bypass the review gate.

## Unchanged

- `node_upsert` and `node_delete` signatures are unchanged; they inherit recovery transparently through `get_or_create_session_branch`.
