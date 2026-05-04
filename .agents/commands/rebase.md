---
description: Rebase the current branch onto the latest base branch, resolving conflicts and optionally force-pushing.
---

# Rebase Branch

## Introduction

Rebase the current branch onto the latest base branch, resolving any merge conflicts by preserving the intent of local changes. Optionally force-push and monitor CI status on GitHub.

## Arguments

<arguments> #$ARGUMENTS </arguments>

**Supported arguments:**

- `push` — After a successful rebase, force-push the branch upstream and monitor GitHub Actions CI until completion.

## Main Tasks

### 1. Assess Current State

- [ ] Verify we are NOT on `stable` or `main`:
  ```bash
  git branch --show-current
  ```
  If on a protected branch, **stop immediately**.
- [ ] Check for uncommitted changes:
  ```bash
  git status --short
  ```
  If there are uncommitted changes, **stop** — rebase requires a clean working tree.
- [ ] Determine the base branch (default: `stable`):
  ```bash
  git log --oneline stable..HEAD | wc -l
  ```
- [ ] Count local commits to know what to expect after rebase:
  ```bash
  git log --oneline stable..HEAD
  ```

### 2. Update Base Branch & Rebase

1. Fetch the latest remote state:
   ```bash
   git fetch origin
   ```
2. Start the rebase:
   ```bash
   git rebase origin/stable
   ```
3. If the rebase completes cleanly, skip to Phase 4.

### 3. Resolve Merge Conflicts

If conflicts occur:

1. Identify conflicting files:
   ```bash
   git diff --name-only --diff-filter=U
   ```
2. For each conflicting file:
   - Read the file and understand both sides of the conflict
   - **Preserve local intent** — our changes take priority since we're landing our work on top of the latest base
   - Resolve the conflict, keeping the logic consistent
   - Stage the resolved file:
     ```bash
     git add <file>
     ```
3. Continue the rebase:
   ```bash
   git rebase --continue
   ```
4. Repeat until all conflicts are resolved.

**When to ask the user:**
- Both sides modify the same logic in incompatible ways
- A file was deleted on one side and modified on the other
- Merge markers appear in generated files

### 4. Verify Rebase Result

1. Run a quick sanity check:
   ```bash
   git log stable..HEAD --oneline
   ```
2. Confirm the commit history looks correct (same number of local commits, no duplicates)
3. Run formatters and linters to catch any resolution issues:
   ```bash
   uv run pre-commit run
   ```
   Fix any issues introduced by conflict resolution.

### 5. Force Push & Monitor CI (only when `push` argument is provided)

**Skip this phase entirely if `push` was NOT passed as an argument.** Instead, inform the user the rebase is complete and they can push when ready.

When `push` IS provided:

1. Force-push the rebased branch:
   ```bash
   git push --force-with-lease origin $(git branch --show-current)
   ```
   Use `--force-with-lease` as a safety measure to avoid overwriting unexpected upstream changes.

2. Monitor GitHub Actions CI (be patient — CI can take several minutes to start):
   ```bash
   gh run list --branch $(git branch --show-current) --limit 5
   ```
   - Check every 30-60 seconds
   - If nothing has started after 5 minutes, investigate whether the push triggered a workflow
3. Wait for CI jobs to complete (check every 30-60 seconds):
   ```bash
   gh run list --branch $(git branch --show-current) --limit 5
   ```
4. If any jobs fail:
   - Read failure logs:
     ```bash
     gh run view <run-id> --log-failed
     ```
   - Analyze the failure and propose a fix to the user
   - After approval, commit the fix, push, and continue monitoring
5. Report final CI status to the user

## Notes

**Branch Safety:**
- This command will NEVER rebase `stable` or `main`
- Uses `--force-with-lease` instead of `--force` to prevent overwriting unexpected remote changes
- Will not proceed with uncommitted changes in the working tree

**Conflict Resolution Strategy:**
- Local changes take priority — the goal is to land *our* work on top of the latest base
- When both sides modify the same logic in incompatible ways, ask the user
- After resolution, run formatters/linters to catch any issues introduced by the merge

## Expected Outcome

A branch that:

- Is cleanly rebased onto the latest `stable`
- Has all merge conflicts resolved preserving local intent
- Passes formatters and linters after resolution
- (When `push` is provided) Is force-pushed upstream with passing CI
