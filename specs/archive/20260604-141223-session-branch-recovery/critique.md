# Critique: Session Branch Recovery & Reset (spec + plan)

Adversarial review through engineering and product lenses. Date 2026-06-04. Severity: 🔴 high / 🟠 medium / 🟡 low.

## Engineering lens

### 🔴 E1 — The per-session `dict` on the shared `AppContext` leaks and has no cleanup hook
The plan replaces the scalar `session_branch` with `session_branches: dict[str, str]` + `_session_locks: dict[str, asyncio.Lock]` keyed by `ctx.session_id`, stored on the **process-wide** `AppContext` (which the #110 bug confirms is shared across sessions). Nothing ever removes entries. Over the life of a streamable-HTTP server, every new MCP session mints a new `session_id` → both dicts grow **unbounded**. The old scalar had no such issue.

- Evidence: FastMCP's own per-session store doesn't help — `ctx.set_state/get_state` write to `self._request_state` (`fastmcp/server/context.py:207,1264`), which is **per-request (per Context)**, not per-session, so it can't hold the branch across tool calls. No session-close callback is exposed that maps to our dict (only a generic `finally` in `mcp/server/lowlevel/server.py:776` unwinding the lifespan stack — which does not touch a dict on the shared `AppContext`).
- **Recommendation**: don't hand-manage a `dict`. Either (a) store the branch on the **per-session object** that gets GC'd when the session ends — mirror FastMCP's own trick (`session._fastmcp_state_prefix`) by stashing on `ctx.request_context.session`; or (b) use a `weakref.WeakKeyDictionary` keyed by that session object on `AppContext`. Both auto-evict on session teardown, give true per-session isolation, and remove the lock-dict bookkeeping. Update `data-model.md` + plan step 1.

### 🟠 E2 — TOCTOU window leaves the customer's exact error reachable; plan marks the fix "optional"
Proactive `status` check happens during `branch.get()`, then the write happens. If the branch is merged in that window, the write fails with the very `"has been merged and is read-only"` error this feature exists to eliminate. `research.md`/`plan.md` label the reactive catch as "optional hardening."
- **Recommendation**: make the reactive net **required**, not optional — on write paths, catch `GraphQLError` matching `read-only`/`has been merged`, clear the session entry, and recover (or at minimum return an actionable "retry — branch was merged" error). For a bug-fix whose success criterion (SC-001) is "next write succeeds," leaving the window open is under-committing.

### 🟠 E3 — Breaking change to `AppContext` not fully called out
Removing the `session_branch` field changes the dataclass constructor. The existing `tests/unit/test_session_branch_validation.py` constructs `AppContext(..., session_branch="…")` and asserts on `app_ctx.session_branch` (lines 34, 45–47, 52, 64, 70, 81). These won't just be "extended" — they break to compile/run. Plan should explicitly list: field removal + every reader migrated (`utils`, `session.py`, `write.py:275`) + test rewrite, so `/speckit-tasks` doesn't under-scope.

### 🟠 E4 — `branch_name_conforms` regex-from-pattern is error-prone
`{user}` is mapped to `[A-Za-z0-9._/-]+`, which includes `/` and is greedy — for a pattern like `mcp/{user}/work-{hex}` it can swallow literal separators, and adjacent placeholder/literal boundaries are tricky to anchor. Risk of both false accepts and false rejects.
- **Recommendation**: build the regex from `string.Formatter().parse()` output (reuse the parsing already in `config._validate_branch_pattern`), escape literals with `re.escape`, use **non-greedy** placeholder classes, anchor `^…$`, and cover it with parametrized tests including adjacent-placeholder cases. Or simplify the rule (e.g., require the configured static prefix + valid charset) if full shape-matching proves brittle.

### 🟡 E5 — `NEED_REBASE`/`NEED_UPGRADE_REBASE` assumed writable without evidence
Treated as "writable" in `data-model.md` with no citation. Plausible but unverified — confirm a rebase-pending branch still accepts writes before relying on it.

## Product lens

### 🔴 P1 — Per-session scoping (FR-010) is scope/risk beyond the reported bug
The customer's actual failure is only the merged-branch staleness (symptoms 1–3), all fixed by **US1 auto-recovery** alone. Per-session scoping is a larger refactor of the state model (and the source of E1). It was a deliberate clarify choice, but it shouldn't gate the customer fix.
- **Recommendation**: ship in two slices. Slice 1 = US1 auto-recovery (merged/deleting → recover) on the existing scalar — small, low-risk, unblocks the customer immediately. Slice 2 = reset tool + per-session scoping (US2/US3/FR-010) with the E1 weakref design. The plan already names US1 the MVP; make the split explicit so Slice 1 can merge without waiting on the riskier refactor.

### 🟠 P2 — SC-002 "100% of write entry points recover" overclaims
`mutate_graphql` with an explicit `branch` (pre-existing param) bypasses `get_or_create_session_branch`, so it gets no recovery and no status check. SC-002 as written is false for that path.
- **Recommendation**: either scope SC-002 to "session-branch-routed writes," or extend recovery/validation to the explicit-branch path too (and decide what "recover" means when the user named the branch).

### 🟠 P3 — `reset_session_branch` name undersells switch/create
One verb "reset" now also switches to and creates branches (Q1/Q2). An agent reading the tool name may not discover the override/create behavior.
- **Recommendation**: reconsider the name (`set_session_branch` / `switch_session_branch`) or, if keeping `reset`, make the tool description + the `server.py` system prompt explicitly state the three behaviors and when to use each.

### 🟡 P4 — Auto-create-on-conformant enables branch sprawl
An agent can call `reset_session_branch("<conformant-name>")` repeatedly and create unlimited branches. There's no cap (`max_branch_retries` only bounds collision retries).
- **Recommendation**: accept the risk (conformance is the guard) but note it; or add a soft cap / require the branch to not already be "many". At least document it.

### 🟡 P5 — Silent branch switch needs an audit trail
Recovery swaps the working branch under the agent. `ctx.warning` informs the live caller, but the human reviewing the eventual proposed change should see provenance.
- **Recommendation**: ensure the audit middleware records recovery/switch events (old→new), not just a transient warning.

## Verdict

The plan is directionally sound and the MVP sequencing is right, but **E1 (leak) and E2 (TOCTOU) are design-level and should be fixed in plan/data-model before `/speckit-tasks`**, and **P1 (slice the per-session refactor out of the customer fix)** is the highest-leverage product call. E3 affects task scoping. The rest are refinements.
