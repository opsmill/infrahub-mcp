# Feature Specification: Session Branch Recovery & Reset

**Feature Branch**: `feat/session-branch-recovery`  
**Created**: 2026-06-04  
**Status**: Completed  
**Input**: User description: "Treat a merged/read-only session branch the same as a missing one (check writability on validation or catch the read-only error on write, clear the cache, recreate); and give a way to reset/override the session branch. Add tests to confirm this use case is covered."

## Context & Problem

The MCP server caches one **session branch** per server process, lazily created on the first write. It is reused for every subsequent write until the process restarts.

Today the cache is only invalidated when the cached branch has been **deleted** (a "branch not found" condition). But in Infrahub a branch that has been **merged** is *not* deleted — it continues to exist as a **read-only** branch. So when an operator merges the session branch (the intended end-of-work action), the cache validation still sees the branch as present and keeps reusing it. Every subsequent write is then routed to a branch that rejects writes, producing errors like `Branch ... has been merged and is read-only`, and there is no in-session way to point writes at a different branch. The write path is effectively wedged until the server restarts.

This was partially addressed previously (stale **deleted** branches are now recovered), but the **merged / read-only** case and the **manual reset** case remain open. This specification covers closing both gaps and adding regression tests.

## Clarifications

### Session 2026-06-04

- Q: How should the manual reset/override capability be exposed? → A: A single write-tagged tool (e.g. `reset_session_branch`) with an optional `branch` argument — omit it to drop the cache and provision a fresh auto branch on the next write; pass a name to switch the current session to that branch.
- Q: When a write or reset targets a branch name that does not yet exist, what should happen? → A: Validate the requested name against the configured branch naming convention (`branch_pattern`); if it conforms, create the branch and explicitly tell the caller it was created; if it does not conform, return an actionable error and create nothing.
- Q: What scope should the session branch / reset / recovery have, given the cache is currently process-wide? → A: Per-session — the session branch is scoped to each MCP session/connection, so recovery and reset affect only the calling session and never disturb other concurrent sessions on the same process.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Writes auto-recover after the session branch is merged or becomes read-only (Priority: P1)

An operator finishes a batch of changes on the auto-created session branch and merges it (the expected workflow). They then continue working in the same session and issue another write. Instead of failing, the write succeeds on a freshly provisioned session branch.

**Why this priority**: This is the customer-blocking defect. Merging the session branch is the *normal, correct* end-of-work step, yet it currently wedges every subsequent write for the lifetime of the server process. Fixing this restores the core write workflow and closes the reported symptoms #1 (mutations rejected as read-only) and #3 (branch-creating mutations also rejected because they route to the dead branch).

**Independent Test**: Simulate a session whose cached branch has been merged (exists but read-only). Issue any write. Verify the write completes successfully on a new branch and the old branch name is no longer used — without restarting the server.

**Acceptance Scenarios**:

1. **Given** a cached session branch that has been merged and is read-only, **When** the operator issues a node create/update, **Then** the cache is cleared, a new writable session branch is provisioned, and the write succeeds on the new branch.
2. **Given** a cached session branch that has been merged and is read-only, **When** the operator issues a GraphQL mutation with no explicit branch, **Then** the mutation succeeds on a newly provisioned branch.
3. **Given** a cached session branch that has been deleted, **When** the operator issues a write, **Then** recovery behaves identically to the merged case (existing behavior preserved — regression guard).
4. **Given** a write was rerouted to a new branch, **When** the operation returns, **Then** the response/notification names both the unavailable previous branch and the new branch.

---

### User Story 2 - Operator can reset the session branch on demand (Priority: P2)

Within a session, an operator decides they want subsequent writes to start on a fresh branch (for example, after an external merge, or to separate a new unit of work) without restarting the server.

**Why this priority**: Provides a deterministic escape hatch so operators are never dependent on automatic detection alone, and gives a clean way to start a new logical change set. Addresses the reported inability to "reset which branch it points at within this session."

**Independent Test**: With an active session branch cached, invoke the reset capability, then issue a write. Verify the write lands on a newly provisioned branch distinct from the previous one.

**Acceptance Scenarios**:

1. **Given** an active cached session branch, **When** the operator resets the session branch, **Then** the next write provisions and targets a new branch.
2. **Given** no session branch has been created yet, **When** the operator resets the session branch, **Then** the operation succeeds and the next write creates the first branch as normal (reset is idempotent / no-op-safe).

---

### User Story 3 - Operator can point the session at an explicitly named branch (Priority: P3)

An operator wants subsequent writes to target a specific branch by name rather than an auto-generated session branch. They do this by passing a target name to the reset/override tool (US2), which switches the current session to that branch.

**Why this priority**: Closes the reported symptom #2 — attempting to target a different branch failed because the named branch did not yet exist. Lower priority because P1 + P2 already unwedge the common workflow; this adds explicit control.

**Independent Test**: Switch the session to a target branch name that does not yet exist, then issue a write. Verify that — when the name conforms to the configured naming convention — the system creates the branch, points the session at it, and the write lands there, without routing to the stale branch.

**Acceptance Scenarios**:

1. **Given** an existing, writable, non-default branch, **When** the operator switches the session to it, **Then** subsequent writes target that branch.
2. **Given** a non-existent branch name that **conforms** to the configured naming convention (`branch_pattern`), **When** the operator switches the session to it, **Then** the system creates the branch, points the session at it, and explicitly reports that a new branch was created.
3. **Given** a non-existent branch name that **does not conform** to the configured naming convention, **When** the operator switches the session to it, **Then** the system returns an actionable error and creates nothing.
4. **Given** the instance default branch, **When** the operator attempts to switch the session to it or write to it, **Then** the request is rejected with the existing default-branch protection message.

---

### Edge Cases

- **Merged vs deleted vs read-only**: All three "cannot accept writes" conditions must trigger the same recovery, regardless of the underlying reason.
- **Fixed-name branch pattern**: When the configured branch pattern has no placeholders, recreating after a merge would collide with the still-existing (read-only) merged branch. The system must surface a clear, actionable error in this case rather than loop or fail opaquely.
- **Concurrent writes (same session)**: Two writes arriving while a session's cached branch is stale must converge on a single new branch (no duplicate branches, no race), consistent with the existing locking around session-branch resolution.
- **Merge during the write window (TOCTOU)**: A branch can be merged between validation and the actual write. The write will fail read-only; the system must clear the cached branch and surface a retryable error rather than stay wedged (FR-011).
- **Per-session isolation**: The session branch is tracked per MCP session/connection. A reset or recovery in one session must not change, clear, or invalidate the branch another concurrent session is using. (This changes today's process-wide caching.)
- **Session identity / transport**: Session-branch state keys off the MCP session/connection identity. Transports or requests without a distinct session identity (e.g. a single stdio session, or stateless requests) must still behave correctly — never falling back to one branch shared across unrelated callers.
- **Default branch unwritable**: Recovery must never resolve to the instance default branch, even if branch discovery is degraded.
- **Repeated failure**: If provisioning a fresh branch itself fails, the operator must receive a clear error rather than an infinite retry or a silent fall-back to the stale branch.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST determine whether the cached session branch can accept writes — covering deleted, merged, and otherwise read-only branches — before routing a write to it.
- **FR-002**: On detecting an unwritable cached session branch, the system MUST clear the cached value, provision a fresh writable branch, and proceed with the requested write, without requiring a server restart.
- **FR-003**: Recovery MUST apply uniformly to every write entry point (node create/update, node delete, and GraphQL mutations that default to the session branch), so no write path can remain wedged to a stale branch.
- **FR-004**: When a write is rerouted to a newly provisioned branch, the system MUST emit a clear, non-fatal notification identifying both the previously cached branch and the newly created branch.
- **FR-005**: The system MUST provide a single write-tagged tool to reset or override the active session branch for the current session. Invoked with no target, it MUST clear the session's cached branch so the next write provisions a fresh one. Invoked with a target branch name, it MUST switch the current session to that branch. Reset MUST be safe (no-op) when no branch is currently cached.
- **FR-006**: When a write or reset targets an explicitly named, non-default branch that does not exist, the system MUST validate the requested name against the configured branch naming convention (`branch_pattern`). If the name conforms, the system MUST create the branch, use it, and explicitly inform the caller that a new branch was created. If the name does not conform, the system MUST return an actionable error and MUST NOT create the branch or silently reroute the write to the cached session branch.
- **FR-007**: The system MUST continue to reject writes targeting the instance default branch (existing protection preserved).
- **FR-008**: Recovery and reset MUST be safe under concurrent writes within the same session — at most one new branch is provisioned per recovery event, with no duplicate branches.
- **FR-009**: The change MUST be covered by automated tests for: merged/read-only recovery (new), deleted-branch recovery (regression), explicit reset, explicit named-branch targeting incl. the not-yet-existing case (both conformant → created and non-conformant → error), and per-session isolation.
- **FR-010**: The active session branch MUST be scoped to each MCP session/connection rather than shared across the whole server process. Recovery and reset MUST affect only the calling session and MUST NOT change or invalidate the branch in use by other concurrent sessions. Per-session state MUST be released when the session ends (no unbounded growth over the server's lifetime).
- **FR-011**: If a write fails because the session branch became read-only/merged *after* validation (a merge during the write window), the system MUST clear the session's cached branch and return an actionable error directing the caller to retry; the retry MUST provision a fresh branch. The session MUST NOT remain wedged on the dead branch, and the system MUST NOT blindly replay an arbitrary mutation.

> **Write-authorization hardening (added after review — see [ADR 0007](../../../dev/adr/0007-per-session-branch-recovery-and-reset.md)).**

- **FR-012**: Writes MUST be confined to the active session branch. `mutate_graphql` MUST NOT accept a per-call branch override (like `node_upsert`/`node_delete`, it always targets the session branch); changing which branch a session uses is only possible via the reset/override tool, which continues to reject the default branch.
- **FR-013**: `mutate_graphql` MUST reject branch-management mutations (`BranchCreate`/`Delete`/`Merge`/`Rebase`/`Update`/`Validate`) and schema mutations, which operate independently of the target branch and would bypass session isolation and the `propose_changes` review gate. When the reset/override tool targets an existing branch, it MUST verify the resolved branch's `is_default` flag (not merely compare names) before allowing it.

### Key Entities *(include if feature involves data)*

- **Session branch**: The write branch tracked **per MCP session/connection** and reused for that session's writes. Has a name, a writability state (writable, read-only/merged, missing), and is provisioned from the configured naming pattern (`branch_pattern`).
- **Branch writability state**: The classification that drives recovery — distinguishing "usable for writes" from "must be replaced" (deleted, merged, or read-only).
- **Default branch**: The instance's protected branch (typically `main`) that writes must never target directly.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After the session branch has been merged or deleted, the very next write succeeds on a fresh branch with **0** manual steps and **0** server restarts.
- **SC-002**: **100%** of **session-branch-routed** write entry points (node create/update, node delete, and `mutate_graphql` without an explicit `branch`) recover from a stale session branch — none remain wedged after the branch becomes unwritable. (Writes that pass an explicit `branch` are outside this guarantee; see FR-006.)
- **SC-003**: An operator can reset the active session branch in a **single** action and confirm the next write targets a different branch.
- **SC-004**: The automated test suite includes passing scenarios for merged, deleted, and read-only stale branches, plus explicit reset and explicit named-branch targeting; all pass in CI.
- **SC-005**: Whenever a write is rerouted to a new branch, the operator receives a message naming both the old and new branch in the same response — no silent branch switch occurs.
- **SC-006**: A reset or recovery in one MCP session has **0** effect on the branch any other concurrent session is using (verified by an isolation test).

## Assumptions

- The session branch is scoped **per MCP session/connection** (a change from today's process-wide caching). Recovery and reset are isolated to the calling session. Identifying the session/connection and the fallback for transports without a distinct session identity are implementation concerns deferred to planning.
- In Infrahub, merging a branch leaves it **present but read-only** (it is not auto-deleted); therefore presence checks alone are insufficient to judge usability — writability must be assessed.
- Reset/override is exposed as a **single write-tagged tool** with an optional target branch (resolved in clarifications), reusing the existing branch-provisioning and default-branch-protection logic.
- The detection mechanism (proactively classifying writability before the write vs. catching the read-only error returned by the write and then recovering) is an implementation decision deferred to planning; either satisfies FR-001/FR-002 as long as the observable behavior — a successful write on a fresh branch without restart — holds.
- Existing default-branch write protection and the existing locking around session-branch resolution remain in force and are reused rather than replaced.
- Audit/logging conventions already present in the write path are reused for the new notifications.
