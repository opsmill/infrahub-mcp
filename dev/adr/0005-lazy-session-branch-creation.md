# 5. Lazy Session Branch Creation with Collision Retry

**Status:** Accepted
**Date:** 2026-04-21
**Author:** @bkohler

## Context

Write operations must be isolated to session branches so that production data on the default branch is never modified directly by an AI agent. This aligns with Infrahub's proposed-changes workflow where all modifications go through a review gate before merging.

Most MCP sessions are read-only (agents querying infrastructure data). Creating a branch at session start would produce orphaned branches that waste Infrahub resources and clutter the branch list. Branch names must be human-readable in the Infrahub UI and support audit trail requirements (who created the branch, when).

## Decision

Session branches are created lazily on the first write operation, not at session start.

- `get_or_create_session_branch()` in `utils.py` is called by write tools. It creates the branch on first invocation and returns the cached branch name on subsequent calls.
- `expand_branch_pattern()` replaces `{date}`, `{hex}`, and `{user}` placeholders in the configurable `branch_pattern` (default: `mcp/session-{date}-{hex}`). `{hex}` uses `secrets.token_hex()` for cryptographic randomness.
- `sanitize_user_for_branch()` applies an 8-rule regex pipeline ensuring git `check-ref-format` compliance: strip email domains, replace unsafe characters, collapse forbidden sequences (`..`, `//`, `/.`), remove trailing `.lock`, trim edges.
- On name collision, the system retries with a fresh `{hex}` value up to `max_branch_retries` (configurable 1–20, default 5) attempts.
- `assert_writable_branch()` blocks any write targeting the instance's default branch, directing users to `propose_changes` instead.

## Consequences

### Positive

- No orphaned branches for read-only sessions (the majority of sessions)
- Pattern-based naming with `{user}` supports audit trail — branch names show who created them
- Collision retry with cryptographic randomness makes conflicts extremely unlikely but handles them gracefully
- Default branch protection prevents accidental production data modification

### Negative

- First write operation has higher latency (branch creation + potential retries)
- Branch names depend on OIDC claims for `{user}` — if claims change (for example, email update), branch naming is inconsistent
- 8-rule sanitization pipeline is complex but necessary for git ref-format edge cases

### Neutral

- Branch is cached on `AppContext` — all subsequent writes in the same session reuse it
- The `{hex}` placeholder is 4 bytes (8 hex chars) — enough entropy for practical uniqueness but short enough to be readable

## Alternatives Considered

### Eager branch creation at session start

Create a branch when the MCP session opens. Rejected: most sessions are read-only queries — eager creation produces orphaned branches that clutter the Infrahub branch list and waste resources.

### Sequential branch numbering

Name branches `mcp/session-001`, `mcp/session-002`, etc. Rejected: requires querying existing branches to find the next number, which is race-prone in concurrent environments and adds a round-trip to every session.

### UUID-based branch names

Use UUIDs for guaranteed uniqueness. Rejected: not human-readable in the Infrahub UI. Operators need to quickly identify which agent session created which branch.
