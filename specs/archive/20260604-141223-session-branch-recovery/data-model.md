# Phase 1 Data Model: Session Branch Recovery & Reset

This feature has no persistent storage. The "data model" is the in-memory state on `AppContext` and the value objects derived from the Infrahub SDK.

## Entity: Per-session branch registry (replaces `AppContext.session_branch`)

`AppContext` (`src/infrahub_mcp/utils.py`) changes from a single scalar to a per-session map.

**Before**
```python
session_branch: str | None = field(default=None)
_session_branch_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
```

**After** (keyed by the per-session OBJECT via weak references — auto-evicts at session end; see research R2 / critique E1)
```python
from weakref import WeakKeyDictionary
# key type is the MCP ServerSession object (ctx.request_context.session); duck-typed at runtime
_session_branches: "WeakKeyDictionary[Any, str]" = field(default_factory=WeakKeyDictionary)
_session_locks: "WeakKeyDictionary[Any, asyncio.Lock]" = field(default_factory=WeakKeyDictionary)
_session_locks_guard: asyncio.Lock = field(default_factory=asyncio.Lock)
```

- `default_branch` + `_default_branch_lock` are **unchanged** (the default branch is instance-wide).
- The scalar `session_branch` and `_session_branch_lock` are **removed** (see Breaking change below).
- Keyed by the session object → a session has **at most one** active branch, and the entry is released when the session object is GC'd (no unbounded growth — FR-010).
- Invariant: only `get_or_create_session_branch` / `reset_session_branch` mutate `_session_branches`, always while holding that session's lock.

⚠️ **Breaking change (critique E3)**: removing the `session_branch` field changes the `AppContext` constructor. Every reader migrates (see table below) and the existing tests in `tests/unit/test_session_branch_validation.py` that pass `session_branch=` and assert on `app_ctx.session_branch` (lines 34, 45–47, 52, 64, 70, 81) must be rewritten to seed/inspect via the new per-session helpers.

## Value object: Session key (the session object)

Storage keys on the per-session object directly; no string key is derived for storage:

```python
def _session_obj(ctx: Context) -> Any:
    rc = ctx.request_context
    if rc is None or getattr(rc, "session", None) is None:
        msg = "request_context.session must not be None"
        raise RuntimeError(msg)
    return rc.session
```

- `ctx.request_context.session` is the same object across tool calls within one client session and distinct per session (stdio/SSE/HTTP); weak-referenceable + identity-hashable → valid `WeakKeyDictionary` key.
- `ctx.session_id` (str) remains available for **display/logging** in `get_session_info`, not for storage.

## Value object: Branch writability (derived from `BranchData.status`)

Classification used by recovery. No new type required — read `branch.status` directly.

| Source signal | Classification | Action |
|---|---|---|
| `BranchNotFoundError` from `branch.get()` | **Missing** (deleted) | clear cache, recreate (existing behavior) |
| `status == BranchStatus.MERGED` | **Unwritable** (read-only) | clear cache, recreate, warn (NEW) |
| `status == BranchStatus.DELETING` | **Unwritable** | clear cache, recreate, warn (NEW) |
| `status ∈ {OPEN, NEED_REBASE, NEED_UPGRADE_REBASE}` | **Writable** | reuse cached branch |

Constant: `_UNWRITABLE_STATUSES = {BranchStatus.MERGED, BranchStatus.DELETING}`.

## Validation rule: explicit target-branch conformance (Q2 / FR-006)

```python
def branch_name_conforms(name: str, pattern: str) -> bool
```

- Returns True iff `name` matches the regex derived from `pattern` (placeholders → `{date}=\d{8}`, `{hex}=[0-9a-f]{8}`, `{user}=[A-Za-z0-9._/-]+?`; literals escaped; anchored). Fixed pattern → exact match.
- **Build it robustly (critique E4)**: derive the regex from `string.Formatter().parse(pattern)` (same parser `config._validate_branch_pattern` uses), `re.escape` each literal segment, use **non-greedy** placeholder classes, and anchor `^…$`. Greedy `{user}` (which allows `/`) can otherwise swallow literal separators in patterns like `mcp/{user}/{hex}`. Cover adjacent-placeholder/boundary cases in parametrized tests.
- Name must also satisfy the allowed branch charset (alphanumeric, `-`, `_`, `.`, `/`); reuse/extend the rules already in `auth.sanitize_user_for_branch`.

## State transitions: a session's branch over its lifecycle

```
(no key)
   │  first write  →  create branch (pattern)            ─┐
   ▼                                                       │ session_branches[key] = "mcp/session-…"
[active: writable]
   │  next write, branch still OPEN/NEED_REBASE  → reuse
   │  next write, branch MERGED/DELETING/missing → recover: del key, create new, warn (old→new)
   │  reset_session_branch()           → del key (next write provisions fresh)
   │  reset_session_branch("feat/x")   → branch exists+writable → key = "feat/x"
   │                                   → branch missing + conformant → create, key = "feat/x", inform
   │                                   → branch missing + non-conformant → ToolError, no change
   │                                   → branch is default / merged → ToolError (reject)
   ▼
[active: new branch]
```

## Touched readers (must become session-aware)

| Reader | File | Change |
|---|---|---|
| `get_or_create_session_branch` | `utils.py:191` | key by `_session_obj`; per-session lock; add `status` check + reactive read-only catch (FR-011) |
| `get_session_branch` (NEW, no-create reader) | `utils.py` | `return app_ctx._session_branches.get(_session_obj(ctx))` |
| `get_session_info` | `tools/session.py:37` | read via `get_session_branch(ctx)` |
| `propose_changes` | `tools/write.py:275` | read via `get_session_branch(ctx)` instead of `app_ctx.session_branch` |
| `reset_session_branch` (NEW tool) | `tools/write.py` | mutate this session's entry (`_session_branches[_session_obj(ctx)]`) |
| `node_upsert` / `node_delete` / `mutate_graphql` (default path) | `tools/write.py` | wrap SDK write to catch read-only/merged `GraphQLError` → clear entry + retryable error (FR-011) |
