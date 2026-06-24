# Quickstart: Session Branch Recovery & Reset

How to exercise the feature once implemented.

## Scenario A — auto-recovery after merge (the customer's bug)

1. Start the server (write mode) against a dev Infrahub.
2. Do a write (e.g. `node_upsert`) → a session branch `mcp/session-…` is created. Confirm via `get_session_info`.
3. Merge that branch into `main` (web UI or proposed change). The branch now has `status=MERGED` and is read-only — it still exists.
4. **Without restarting the server**, do another write.
   - **Expected**: the write succeeds on a *new* `mcp/session-…` branch; the response/log names the old (merged) branch and the new one. No "has been merged and is read-only" error.

## Scenario B — manual reset

1. With an active session branch, call `reset_session_branch()` (no args). → `{"action":"reset","session_branch":null,...}`.
2. Next write provisions a fresh branch.

## Scenario C — switch/override to a named branch

1. Call `reset_session_branch(branch="mcp/session-20260604-deadbeef")` (a name that conforms to `branch_pattern` but doesn't exist).
   - **Expected**: branch created, session switched, `{"action":"created","created":true,...}`.
2. Call `reset_session_branch(branch="totally-random-name")` (non-conformant).
   - **Expected**: `ToolError` explaining the name doesn't match the configured convention; nothing created.
3. Call `reset_session_branch(branch="main")` (default).
   - **Expected**: rejected with the default-branch protection message.

## Scenario D — per-session isolation

1. Open two MCP client sessions (distinct `mcp-session-id`).
2. Each does a write → each gets its **own** session branch.
3. Session 1 calls `reset_session_branch()`.
   - **Expected**: session 2's branch is unchanged; its next write still targets its original branch.

## Verification (gates)

```bash
uv sync
uv run pytest tests/unit/test_session_branch_validation.py -x   # targeted
uv run invoke format lint                                       # ruff + mypy + pylint + yaml
uv run pytest                                                   # full suite
```

Tests to add/extend in `tests/unit/test_session_branch_validation.py` (+ a new test module for the tool): merged-status recovery, DELETING-status recovery, deleted-branch recovery (regression), reset-to-empty, switch-to-existing, create-on-conformant, error-on-nonconformant, reject-default, and per-session isolation.
