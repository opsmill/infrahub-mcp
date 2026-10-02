# 7. Per-Session Branch Recovery, Reset, and Scoping

**Status:** Accepted
**Date:** 2026-06-04
**Author:** @bkohler

## Context

[ADR 0005](0005-lazy-session-branch-creation.md) introduced a lazily-created session branch cached on `AppContext`. Two gaps surfaced in production:

1. The cache was only invalidated when the branch was **deleted** (`BranchNotFoundError`). But merging a branch in Infrahub does **not** delete it — it stays present and becomes **read-only** (`BranchStatus.MERGED`). After an operator merged the session branch (the normal end-of-work step), every subsequent write was routed to a read-only branch and failed (`"Branch ... has been merged and is read-only"`), wedging the write path until the server restarted.
2. `AppContext` is shared across MCP sessions for the process lifetime, so a single cached `session_branch` was effectively process-global: one session's branch (and any reset/recovery) affected all sessions. There was also no way to reset or switch the branch within a session.

## Decision

- **Per-session scoping.** Replace the `session_branch` scalar with `WeakKeyDictionary` maps on `AppContext` keyed by the per-session object (`ctx.request_context.session`, via `_session_obj()`): one for the active branch name, one for a per-session `asyncio.Lock` (created lazily under a guard lock). Weak keys release entries automatically when a session ends — no unbounded growth — and isolate sessions from each other.
- **Proactive recovery.** `get_or_create_session_branch()` validates the cached branch with the existing single `client.branch.get()` and now also inspects `BranchData.status`. A status in `{MERGED, DELETING}` (read-only / being removed) is treated like a missing branch: the entry is cleared and a fresh branch is provisioned, warning the caller with **both** the old and new branch names. Writable statuses (`OPEN`, `NEED_REBASE`, `NEED_UPGRADE_REBASE`) are reused.
- **Reactive recovery (TOCTOU).** A branch can be merged between validation and the write. The write tools (`node_upsert`, `node_delete`, `mutate_graphql`) catch a read-only/merged-looking `GraphQLError` and then **confirm via `client.branch.get()` status that the branch is actually merged/deleted before clearing it** — the error text alone is ambiguous (a read-only *attribute* error reads the same), and clearing on a false positive would orphan the user's work on a still-writable branch. Only when confirmed stale do they clear the session entry (under the per-session lock) and raise a retryable error. The failed mutation is **not** replayed (an arbitrary mutation could partially apply).
- **Explicit reset/override.** A new write-tagged tool `reset_session_branch(branch=None)`: with no argument it clears the session's branch (next write provisions a fresh one); with a name it switches the session to that branch — created when the name conforms to the configured `branch_pattern` (`branch_name_conforms()`), and rejected for the default branch or a merged/read-only branch.

### Write-authorization hardening

A review of the write path surfaced ways an agent could write outside its session branch or reach the default branch, bypassing the `propose_changes` review gate. Hardened as follows:

- **Writes pinned to the session branch.** `mutate_graphql` no longer accepts a per-call `branch` override — like `node_upsert`/`node_delete`, it always targets the active session branch. Changing which branch a session uses is only possible deliberately via `reset_session_branch` (still default-blocked). This removes the ability to transiently aim a write at an arbitrary (e.g. another session's) feature branch.
- **Privileged mutations blocked.** `mutate_graphql` now parses the query AST and rejects non-mutation operations and — scanning field names **recursively through inline fragments and fragment definitions** so they can't be smuggled in via `... on Mutation { ... }` — Infrahub branch-management mutations (`BranchCreate/Delete/Merge/Rebase/Update/Validate`) and schema mutations (`SchemaDropdown*`, `SchemaEnum*`). These operate independently of the target branch — `BranchMerge` on the session branch would merge it into the default branch with no human review. The denylist tracks infrahub-sdk's built-in names and must be updated if the SDK adds more.
- **Robust default-branch guard.** When `reset_session_branch` targets an existing branch, it checks the resolved branch's `is_default` flag, not just a name compare against the cached default — closing case/alias variants that an exact string match would miss.

## Consequences

### Positive

- Merging the session branch no longer wedges writes — recovery is automatic and requires no restart (the original customer bug).
- Sessions are isolated: a reset/recovery in one session never disturbs another.
- No memory growth from accumulating session ids — entries die with the session.
- The status check reuses the existing `branch.get()` round-trip, so the hot write path adds no extra calls.
- Operators have an explicit escape hatch to reset or switch branches mid-session.
- Writes cannot escape the session branch, and an agent cannot merge to / delete the default branch via `mutate_graphql` — the `propose_changes` review gate can no longer be bypassed.

### Negative

- `reset_session_branch` with a conformant name can create branches, a minor branch-sprawl vector (bounded only by the naming convention).
- Fixed-name `branch_pattern` (no placeholders) cannot recover after a merge — the merged branch still occupies the name; the system returns a clear, actionable error directing the operator to use a `{hex}`/`{date}` pattern.
- Removing `mutate_graphql`'s `branch` argument is a tool API contract change; callers that passed an explicit branch must switch the session via `reset_session_branch` instead.
- The blocked-mutation denylist must be kept in sync with Infrahub-SDK built-ins (a maintenance cost; a new privileged mutation would not be blocked until added).

### Neutral

- Recovery is observable via the `ctx.warning` (old→new) and the tool result's `branch` field; the audit middleware records the enclosing tool call.
- Per-session state keys on the session object rather than `ctx.session_id` (a string); the object is the natural weak-ref anchor and avoids a never-cleaned string-keyed dict.

## Alternatives Considered

### Keep the process-wide scalar, only add the merged-status check

Fixes the merge bug but leaves the cross-session sharing problem (one session's branch visible to all). Rejected — the sharing is itself a latent correctness issue.

### `dict[str, str]` keyed by `ctx.session_id`

Per-session, but a string-keyed dict on the shared `AppContext` is never cleaned up — it grows unbounded over the process lifetime (every HTTP session mints a new id). FastMCP's `set_state`/`get_state` is per-request, not per-session, so it can't hold the branch across calls. Rejected in favor of `WeakKeyDictionary` keyed by the session object, which auto-evicts.

### Reactive-only detection (catch the read-only error, recover, retry)

Performs a doomed write first and relies on matching server error strings. Kept only as a defense-in-depth net for the TOCTOU window; the proactive `status` check is the primary mechanism.
