---
description: Handle the full workflow from current branch state to an open, CI-monitored pull request.
---

# Open Pull Request

## Introduction

Handle the full workflow from current branch state to an open, CI-monitored pull request. This command enforces branch discipline, analyzes all branch changes for a business-value-focused description, ensures documentation is current, and requires user approval at every step.

## Arguments

<arguments> #$ARGUMENTS </arguments>

**Supported arguments:**

- `commit` — Stage, commit, and push uncommitted changes before proceeding. **Without this argument, no commits are made** — the command works only with what is already committed on the branch.

## Main Tasks

### 1. Safety Checks & Branch Setup

- [ ] Verify we are NOT on `stable` or `main`:
  ```bash
  git branch --show-current
  ```
  If on a protected branch, **stop immediately** and inform the user.
- [ ] Check working tree status:
  ```bash
  git status --short
  ```
  If there are uncommitted changes and `commit` was NOT passed, **warn the user** but do not commit.
- [ ] Ensure the branch tracks a remote:
  ```bash
  git rev-parse --abbrev-ref --symbolic-full-name @{u} 2>/dev/null || echo "no upstream"
  ```
  If no upstream, set one:
  ```bash
  git push -u origin $(git branch --show-current)
  ```

### 2. Commit Changes (only when `commit` argument is provided)

**Skip this phase entirely if `commit` was NOT passed as an argument.**

When `commit` IS provided:

1. Run the required quality gates:
   ```bash
   uv run pre-commit run
   ```
   Fix any issues that arise before committing.
2. Stage all changes:
   ```bash
   git add -A
   ```
3. Create a commit with a descriptive message following project conventions.
4. Push to remote:
   ```bash
   git push
   ```

### 3. Analyze All Branch Changes

<thinking>
Don't just look at the latest commit — analyze ALL changes since diverging from stable. The PR description must cover everything.
</thinking>

1. Find the merge base with `stable`:
   ```bash
   git merge-base stable HEAD
   ```
2. Review all commits on this branch:
   ```bash
   git log stable..HEAD --oneline
   ```
3. Review the full diff:
   ```bash
   git diff stable...HEAD --stat
   ```
4. Read changed files to understand the full scope of changes.
5. Check if a spec exists for this work (look in `.specify/` or `specs/`).

### 4. Documentation Review

<thinking>
Stale docs are worse than no docs. Check what changed and whether documentation needs updating.
</thinking>

For each significant change, verify documentation is current:

- [ ] **New tools/resources/prompts?** → Check `docs/docs/` for user-facing documentation
- [ ] **Architecture changes?** → Check `dev/knowledge/architecture.md`
- [ ] **New coding patterns?** → Check `dev/guidelines/python.md`
- [ ] **Architectural decisions?** → Check if a new ADR in `dev/adr/` is warranted
- [ ] **Configuration changes?** → Check `docs/docs/` for updated config reference
- [ ] **README changes?** → Check root `README.md` if user-facing behavior changed

If any documentation is missing or stale:
1. Propose the documentation updates to the user
2. After approval, make the updates and commit them
3. Run `uv run rumdl check docs/docs/` if any `.mdx` files were modified

### 5. Draft PR Description

<thinking>
Focus on business value — what problem does this solve, what capability does it add? The reviewer should understand WHY before they look at HOW. Reference the spec if one exists.
</thinking>

**PR Title:** Short, conventional format (under 70 chars). Examples:
- `feat: add response caching middleware with configurable TTLs`
- `fix: handle SDK timeout errors in node search tools`
- `refactor: extract auth provider factory into dedicated module`

**PR Body Template:**

```markdown
## Summary
[1-3 sentences: what business problem this solves or what capability it adds.
Frame as outcomes for users/operators, not as code changes.]

## Key Changes
[Bulleted list of the most important changes, framed as outcomes:
- "MCP clients can now cache schema responses" NOT "Added ResponseCachingMiddleware"
- "Auth tokens are validated per-request via ContextVar" NOT "Changed auth.py"]

## Spec Reference
[If tied to a spec: link to the spec, highlight key requirements addressed.
Omit this section if no spec exists.]

## Documentation Updates
[List any dev/ or docs/ files that were added or updated as part of this PR.
Omit this section if no docs were changed.]

## Test Plan
[How to verify — test commands to run, manual verification steps, or CI checks to watch]
```

**Labels:** Choose from repo labels (`gh label list`). Common ones:
- `bugs`, `enhancements`, `features`, `breaking`
- Improvements = **enhancements** unless explicitly a **feature**

### 6. User Validation & PR Creation

1. Present the complete PR title, body, and labels to the user
2. Wait for explicit approval or requested changes
3. Only after approval, create the PR:
   ```bash
   gh pr create --title "<title>" --body "<body>" --label "<labels>" --base stable
   ```
4. Report the PR URL to the user

### 7. Monitor CI & Fix Issues

<thinking>
Don't just open the PR and walk away. Watch CI, especially linters — they frequently catch issues. Fix them proactively.
</thinking>

1. After PR creation, wait for CI to start and monitor GitHub Actions (check every 30-60 seconds):
   ```bash
   gh run list --branch $(git branch --show-current) --limit 5
   ```
   CI can take a few minutes to start. If nothing has started after 5 minutes, investigate.

2. Wait for at least all **linter jobs** to complete
3. If any jobs fail:
   - Read failure logs:
     ```bash
     gh run view <run-id> --log-failed
     ```
   - Reproduce the issue locally:
     ```bash
     uv run pre-commit run
     uv run pytest
     ```
   - Analyze the failure and propose a fix to the user
   - After approval, commit the fix and push
   - Continue monitoring until linters pass
4. Report final CI status to the user

## Notes

**Branch Safety:**
- This command will NEVER commit to `stable` or `main`
- If uncommitted changes exist and `commit` was not passed, warn but do not commit

**Business Value Focus:**
- PR descriptions should answer "why does this matter?" before "what changed?"
- When a spec exists, it is the primary framing device — reference user scenarios and success criteria
- Technical implementation details belong in the diff, not the PR description

**Documentation Discipline:**
- Stale docs are worse than no docs — always check before opening a PR
- New features or changed behavior should be reflected in `dev/knowledge/` or `dev/guidelines/`

## Expected Outcome

A pull request that:

- Lives on a properly named feature branch (never `stable` or `main`)
- Has a business-value-focused description referencing specs when available
- Includes up-to-date developer documentation
- Has been reviewed and approved by the user before creation
- Has passing CI linters (with fixes pushed if needed)
