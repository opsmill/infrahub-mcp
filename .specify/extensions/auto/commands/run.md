---
description: Run the full speckit workflow end-to-end — specify, plan, critique, tasks, implement, review, extract — making all decisions autonomously.
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Outline

You are running the **full speckit pipeline** end-to-end. The user's input (above) is the feature description that will seed the specification phase.

Execute every phase below **in order**, making all decisions autonomously. Do not stop to ask the user for input between phases — if a phase requires choices (e.g., clarification questions in specify, research decisions in plan), use your best judgment and proceed. The user expects a hands-off, one-shot execution.

After **each phase**, invoke the `speckit-checkpoint-commit` skill to commit the artifacts produced by that phase before moving on.

> Each phase below is executed by invoking the named skill (e.g. via the agent's Skill tool). Skills are agent-agnostic, so this workflow runs identically across any harness that supports skill discovery — not only those exposing speckit slash commands.

### Phase 1 — Specify

Invoke the `speckit-specify` skill with the user's feature description (`$ARGUMENTS`).

- Complete the full specify workflow: generate a short name, create the spec directory, write `spec.md`, run quality checks.
- If clarification questions arise, answer them yourself based on context and best judgment — do **not** pause for user input.
- Commit the spec artifacts.

### Phase 2 — Plan

Invoke the `speckit-plan` skill.

- Complete the full plan workflow: research unknowns, generate `plan.md`, `research.md`, `data-model.md`, API contracts, `quickstart.md`.
- Make all design decisions autonomously.
- Commit the plan artifacts.

### Phase 3 — Critique

Invoke the `speckit-critique-run` skill.

- Run the dual-lens (Product + Engineering) critique against `spec.md` and `plan.md` before any tasks are generated.
- For any 🎯 **Must-Address** findings, apply the suggested fixes to `spec.md` / `plan.md` autonomously and commit them — do not pause for user approval.
- For 💡 Recommendations, apply them when the fix is clear and low-risk; otherwise note and move on.
- 🤔 Questions: resolve with your best judgment based on context (same rule as the Specify phase).
- If the verdict is 🛑 **RETHINK**, loop back to `speckit-plan` (or `speckit-specify` if the spec itself is the problem), re-run the critique, then continue.
- Commit the critique report and any spec/plan updates before moving on.

### Phase 4 — Tasks

Invoke the `speckit-tasks` skill.

- Generate the full `tasks.md` with dependency-ordered, actionable tasks.
- Skip the optional `speckit-analyze` skill unless something looks inconsistent — use your judgment.
- Commit the tasks artifact.

### Phase 5 — Implement

Invoke the `speckit-implement` skill.

- Execute all tasks from `tasks.md` phase by phase.
- Commit at natural implementation checkpoints (after each task or logical group of tasks).
- Run formatters and linters as required by the project.
- If tests fail, fix them before moving on.

### Phase 6 — Review

Invoke the `speckit-review-run` skill.

- Run the comprehensive review across all enabled agents.
- For any findings rated **high severity or above**, fix them immediately and commit the fixes.
- For lower-severity findings, note them but do not block progress.

### Phase 7 — Extract

Invoke the `speckit-extract-run` skill.

- Extract ADRs, knowledge, and guidelines from the completed spec into `dev/`.
- Commit the extracted documentation.

## Completion

After all phases are complete, provide a brief summary:
- Feature name and spec directory
- Number of tasks completed
- Any review findings that were fixed
- Any notable decisions you made autonomously
