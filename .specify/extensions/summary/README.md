# Session Summary Extension for Spec Kit

Manual, flow-level summary of the current Claude Code session. Captures
the *story* of a working session — what was attempted, decided, and
shipped — in a single short markdown document next to `spec.md` and
`plan.md`.

## Usage

```bash
/speckit.summary.run [--since <commit|time>]
```

Run on demand, typically at the end of a session or before a context
hand-off. The command:

1. Resolves the active feature directory from the current branch.
2. Reads the live conversation and (optionally) recent `git log`.
3. Writes `FEATURE_DIR/sessions/session-YYYY-MM-DD-HHMM.md`.
4. Prints the resolved path.

If you are not on a feature branch, the command refuses to run.

## What good output looks like

```markdown
# Session Summary — 2026-05-01 14:30

## Executive Summary

Stabilized the failing E2E run on the deployments-create flow. The
root cause turned out to be driver init order, not the new GraphQL
field as initially suspected. Session ended with a green suite and an
open PR.

## Timeline

- 13:50 — pulled latest develop, reproduced failing E2E locally
- 14:02 — suspected new `cluster.fqdn` field, ran propagation tests
- 14:18 — ruled out schema regression; pivoted to driver init
- 14:25 — patched init order in `driver/registry.py`
- 14:33 — full E2E suite green
- 14:40 — opened PR #178

## Outcomes

- Opened PR #178 (driver init order fix).
- Materially changed `driver/registry.py`, `backend/styrmin_backend/services/deployment.py`.
- Decided: cluster.fqdn change is unrelated; keep as-is.
- Deferred: refactoring the driver registry into a proper DI container.
```

Notice what is **not** there: no diffs, no line numbers, no per-tool
narration, no copy-pasted error messages. The unit of information is
the *phase of work*, not the *tool call*.

## When to run it

- Before stepping away from a long session, so a teammate (or you, the
  next morning) can pick up the thread.
- Before a reviewer looks at the PR — they get the narrative shape
  before they read the diff.
- After a debugging session where the *path* to the fix is more
  interesting than the fix itself.

## How it differs from neighbouring extensions

| Command | Unit | Lifetime | Trigger |
|---------|------|----------|---------|
| `/speckit.summary.run` | Single working session | Ephemeral, per-session | Manual, end-of-session |
| `/speckit.archive.run` | Whole feature | Permanent, after merge | Manual, end-of-feature |
| `/speckit.reconcile.run` | Single feature artifact | Updates spec/plan/tasks | When implementation drifts |

`speckit.archive` is the long-form story, written once per feature and
preserved in project memory. `summary` is the short-form story
of one working session — useful at the moment, not load-bearing
afterwards. `reconcile.run` is mechanical (artifact updates), not
narrative.

## Output location

Summaries live at:

```text
specs/<feature>/sessions/session-YYYY-MM-DD-HHMM.md
```

They sit next to `spec.md` / `plan.md` so they travel with the feature
in git. If you would rather not commit them, add the path to your
local `.git/info/exclude`; the extension does not gitignore them by
default because the value of a session summary is mostly to *other
people*.

## Hooks

None. This is a manual-only command — a session boundary is a human
judgment call. It is not invoked from any speckit hook.

## License

MIT
