# Speckit Commands & Extensions Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring `infrahub-mcp` to speckit v0.8.1 parity with `../styrmin` — add slash-command files for every existing skill, bump the base speckit scaffolding, install the curated extensions (review, tinyspec, iterate, summary, retrospect, archive, extract.run, reconcile, critique, checkpoint, auto), and wire up matching skills + commands.

**Architecture:** Speckit ships three coupled artifacts per command — a Claude/Amp/Copilot **slash command** at `.agents/commands/<name>.md`, an agent-agnostic **skill** at `.agents/skills/<name>/SKILL.md`, and an **extension package** at `.specify/extensions/<id>/` (for everything beyond the core). Everything is plain text — copy from `../styrmin/` and patch project-specific overrides. Two manifest files at `.specify/integrations/{speckit,claude}.manifest.json` and the `.specify/extensions/.registry` track installed versions; we update them last so partial states don't lie about installed state. Project-owned files (`.specify/memory/constitution.md`, `.specify/templates/adr-template.md`, `init-options.json` `branch_numbering=timestamp`) are NEVER overwritten.

**Tech Stack:** Markdown (skills + commands), YAML (extension manifests), JSON (integration manifests), bash (speckit scripts). No code execution — pure file operations + a final `find` smoke test.

---

## Decisions To Confirm Before Starting

These are flagged for the user to confirm during plan review. Defaults are coded into the tasks below.

1. **Hook chain in `extensions.yml`** — styrmin auto-commits before each speckit phase. Default: adopt styrmin's full chain (Phase 8). Alternative: keep current minimal hooks.
2. **Existing `speckit.extract.md`** — local variant extracts to `dev/`; styrmin's `speckit.extract.run.md` extension extracts to a configurable target. Default: keep the local one as `speckit.extract.md` (project-tuned), additionally install `speckit.extract.run.md` extension under a different name.
3. **Non-speckit skills (`dev-validate/`, `e2e-troubleshoot/`)** — styrmin-specific (Rust CLI, e2e suite). Default: skip.
4. **Non-speckit commands (`pr.md`, `rebase.md`, `create-issue.md`)** — already present as commands in infrahub-mcp; styrmin also has them as skills. Default: out of scope for this plan.

---

## Source of Truth

- **Source repo:** `/Users/bkohler/automation/opsmill/styrmin` (speckit v0.8.1, installed 2026-04-25)
- **Target repo:** `/Users/bkohler/automation/opsmill/infrahub-mcp` (speckit v0.7.3)
- All `cp`/`rsync` commands below use absolute paths so the plan is location-independent.

---

## File Structure

### Files we ADD (new, copied verbatim from styrmin)

```
.agents/commands/
  speckit.analyze.md, speckit.checklist.md, speckit.clarify.md, speckit.constitution.md,
  speckit.git.commit.md, speckit.git.feature.md, speckit.git.initialize.md,
  speckit.git.remote.md, speckit.git.validate.md, speckit.implement.md,
  speckit.plan.md, speckit.specify.md, speckit.tasks.md, speckit.taskstoissues.md       # Phase 1
  speckit.tinyspec.{tinyspec,classify,implement}.md (+ .agent.md siblings)              # Phase 4
  speckit.review.md, speckit.review.run.md, speckit.review.{code,comments,errors,
    simplify,tests,types}.md (+ .agent.md siblings)                                     # Phase 5
  speckit.summary.run.md (+ .agent.md), speckit.retrospect.run.md (+ .agent.md),
  speckit.archive.run.md, speckit.extract.run.md (+ .agent.md)                          # Phase 6
  speckit.iterate.{define,apply}.md, speckit.reconcile.run.md,
  speckit.critique.run.md, speckit.checkpoint.commit.md (+ .agent.md),
  speckit.auto.run.md (+ .agent.md)                                                     # Phase 7

.agents/skills/
  speckit-tinyspec-{tinyspec,classify,implement}/SKILL.md                               # Phase 4
  speckit-review/SKILL.md, speckit-review-{run,code,comments,errors,
    simplify,tests,types}/SKILL.md                                                      # Phase 5
  speckit-summary-run/, speckit-retrospect-run/, speckit-archive/,
  speckit-extract-run/                                                                  # Phase 6
  speckit-iterate-{define,apply}/, speckit-reconcile-run/, speckit-critique-run/,
  speckit-checkpoint-commit/, speckit-auto-run/                                         # Phase 7

.specify/extensions/
  archive/, auto/, checkpoint/, critique/, extract/, iterate/, reconcile/,
  retrospect/, review/, summary/, tinyspec/                                             # Phases 4-7
  .registry                                                                             # Phase 7 final
```

### Files we OVERWRITE (speckit core, no project content)

```
.specify/scripts/bash/{common.sh,create-new-feature.sh,setup-plan.sh,update-agent-context.sh}   # Phase 2
.specify/templates/{checklist-template.md,plan-template.md,tasks-template.md,agent-file-template.md}  # Phase 2
.specify/integration.json                                                                # Phase 2
.specify/integrations/{claude.manifest.json,speckit.manifest.json}                       # Phase 2 + after each ext
.specify/extensions.yml                                                                  # Phase 8
.agents/skills/speckit-{analyze,checklist,clarify,implement,specify}/SKILL.md            # Phase 3
```

### Files we PRESERVE (project-specific, must not change)

```
.specify/memory/constitution.md                  # 261-line infrahub-mcp constitution
.specify/templates/adr-template.md               # infrahub-mcp ADR template (absent in styrmin)
.specify/init-options.json                       # only update speckit_version; keep branch_numbering=timestamp
.agents/commands/{create-issue,pr,rebase,speckit.extract}.md  # local commands
.agents/skills/README.md                         # local agent-skills doc
```

---

## Phase 1 — Sync slash commands for the 14 already-installed skills

The user's primary pain point: skills exist but the matching `.agents/commands/<name>.md` files don't, so `/speckit.specify` etc. don't appear in Claude Code's slash-command picker. Fix this first — it unblocks daily use independently of everything else.

### Task 1.1: Copy the 14 missing speckit command files

**Files:**
- Create: `.agents/commands/speckit.{analyze,checklist,clarify,constitution,git.commit,git.feature,git.initialize,git.remote,git.validate,implement,plan,specify,tasks,taskstoissues}.md`

- [ ] **Step 1: Copy commands**

```bash
cd /Users/bkohler/automation/opsmill/infrahub-mcp
for f in speckit.analyze.md speckit.checklist.md speckit.clarify.md speckit.constitution.md \
         speckit.git.commit.md speckit.git.feature.md speckit.git.initialize.md \
         speckit.git.remote.md speckit.git.validate.md speckit.implement.md \
         speckit.plan.md speckit.specify.md speckit.tasks.md speckit.taskstoissues.md; do
  cp "/Users/bkohler/automation/opsmill/styrmin/.agents/commands/$f" ".agents/commands/$f"
done
```

- [ ] **Step 2: Verify all 14 files now exist**

Run: `ls .agents/commands/speckit.*.md | wc -l`
Expected: `15` (14 new + the existing `speckit.extract.md`)

- [ ] **Step 3: Verify YAML frontmatter parses**

Run: `for f in .agents/commands/speckit.*.md; do head -1 "$f" | grep -q '^---$' || echo "BAD: $f"; done`
Expected: no output (all have valid frontmatter delimiters)

- [ ] **Step 4: Commit**

```bash
git add .agents/commands/speckit.*.md
git commit -m "feat(.agents): add slash-command files for the 14 existing speckit skills"
```

---

## Phase 2 — Bump speckit base scaffolding 0.7.3 → 0.8.1

Updates speckit core scripts, templates, and version metadata. Preserves project-specific files: `constitution.md` (project content), `adr-template.md` (project-only), `init-options.json` `branch_numbering` setting.

### Task 2.1: Replace speckit bash scripts with v0.8.1

**Files:**
- Overwrite: `.specify/scripts/bash/{common.sh,create-new-feature.sh,setup-plan.sh}`
- Create: `.specify/scripts/bash/update-agent-context.sh`

- [ ] **Step 1: Copy scripts**

```bash
cd /Users/bkohler/automation/opsmill/infrahub-mcp
cp /Users/bkohler/automation/opsmill/styrmin/.specify/scripts/bash/common.sh .specify/scripts/bash/common.sh
cp /Users/bkohler/automation/opsmill/styrmin/.specify/scripts/bash/create-new-feature.sh .specify/scripts/bash/create-new-feature.sh
cp /Users/bkohler/automation/opsmill/styrmin/.specify/scripts/bash/setup-plan.sh .specify/scripts/bash/setup-plan.sh
cp /Users/bkohler/automation/opsmill/styrmin/.specify/scripts/bash/update-agent-context.sh .specify/scripts/bash/update-agent-context.sh
chmod +x .specify/scripts/bash/*.sh
```

- [ ] **Step 2: Sanity check — `bash -n` on every script**

Run: `for f in .specify/scripts/bash/*.sh; do bash -n "$f" || echo "SYNTAX ERROR: $f"; done`
Expected: no output

- [ ] **Step 3: Commit**

```bash
git add .specify/scripts/bash/
git commit -m "chore(.specify): bump speckit bash scripts to v0.8.1"
```

### Task 2.2: Replace speckit core templates with v0.8.1

**Files:**
- Overwrite: `.specify/templates/{checklist-template.md,plan-template.md,tasks-template.md}`
- Create: `.specify/templates/agent-file-template.md`
- Preserve: `.specify/templates/adr-template.md`, `.specify/templates/spec-template.md`, `.specify/templates/constitution-template.md`

- [ ] **Step 1: Confirm `spec-template.md` and `constitution-template.md` are unchanged**

Run: `diff -q /Users/bkohler/automation/opsmill/styrmin/.specify/templates/spec-template.md .specify/templates/spec-template.md; diff -q /Users/bkohler/automation/opsmill/styrmin/.specify/templates/constitution-template.md .specify/templates/constitution-template.md`
Expected: no output (already identical between repos)

- [ ] **Step 2: Copy the templates that differ + the new one**

```bash
cp /Users/bkohler/automation/opsmill/styrmin/.specify/templates/checklist-template.md .specify/templates/checklist-template.md
cp /Users/bkohler/automation/opsmill/styrmin/.specify/templates/plan-template.md .specify/templates/plan-template.md
cp /Users/bkohler/automation/opsmill/styrmin/.specify/templates/tasks-template.md .specify/templates/tasks-template.md
cp /Users/bkohler/automation/opsmill/styrmin/.specify/templates/agent-file-template.md .specify/templates/agent-file-template.md
```

- [ ] **Step 3: Verify ADR template is still present (project-specific, must not have been clobbered)**

Run: `test -f .specify/templates/adr-template.md && echo OK`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add .specify/templates/
git commit -m "chore(.specify): bump speckit core templates to v0.8.1; preserve adr-template"
```

### Task 2.3: Bump version metadata in `integration.json` and `init-options.json`

**Files:**
- Modify: `.specify/integration.json` — single field `"version"`
- Modify: `.specify/init-options.json` — bump `speckit_version`, add `preset: null`, KEEP `branch_numbering: "timestamp"`

- [ ] **Step 1: Update `.specify/integration.json`**

Replace the file contents with:

```json
{
  "integration": "claude",
  "version": "0.8.1"
}
```

- [ ] **Step 2: Update `.specify/init-options.json` — only the speckit-managed fields**

Replace the file contents with (note: `branch_numbering` stays `timestamp` per project preference):

```json
{
  "ai": "claude",
  "branch_numbering": "timestamp",
  "force": false,
  "ignore_agent_tools": false,
  "no_git": false,
  "preset": null,
  "script": "sh",
  "speckit_version": "0.8.1"
}
```

- [ ] **Step 3: Commit**

```bash
git add .specify/integration.json .specify/init-options.json
git commit -m "chore(.specify): bump speckit version metadata to 0.8.1"
```

### Task 2.4: Refresh installation manifests

**Files:**
- Overwrite: `.specify/integrations/speckit.manifest.json`
- Overwrite: `.specify/integrations/claude.manifest.json`

These manifests track file hashes; replacing them with styrmin's copies aligns the recorded hashes with the v0.8.1 file contents we just installed.

- [ ] **Step 1: Copy speckit.manifest.json**

```bash
cp /Users/bkohler/automation/opsmill/styrmin/.specify/integrations/speckit.manifest.json .specify/integrations/speckit.manifest.json
```

- [ ] **Step 2: Copy claude.manifest.json**

(This file lists hashes for the 9 core speckit skills; we'll re-sync those skills in Phase 3, after which the recorded hashes will be correct.)

```bash
cp /Users/bkohler/automation/opsmill/styrmin/.specify/integrations/claude.manifest.json .specify/integrations/claude.manifest.json
```

- [ ] **Step 3: Verify file hashes match what manifest claims (post-Phase-3 — defer for now)**

Run: `python3 -c "import json,hashlib,sys; m=json.load(open('.specify/integrations/speckit.manifest.json')); [print('OK' if hashlib.sha256(open(p,'rb').read()).hexdigest()==h else f'MISMATCH: {p}') for p,h in m['files'].items()]"`
Expected: every line `OK`. If any `MISMATCH:`, those are files Phase 3 will sync — they will resolve there.

- [ ] **Step 4: Commit**

```bash
git add .specify/integrations/
git commit -m "chore(.specify): refresh integration manifests for speckit 0.8.1"
```

---

## Phase 3 — Sync the 5 differing existing skills

Diff already showed 5 of 14 existing skills differ between v0.7.3 and v0.8.1: `speckit-{analyze,checklist,clarify,implement,specify}`. The other 9 are byte-identical and need no change.

### Task 3.1: Overwrite the 5 stale SKILL.md files

**Files:**
- Overwrite: `.agents/skills/speckit-{analyze,checklist,clarify,implement,specify}/SKILL.md`

- [ ] **Step 1: Copy each SKILL.md**

```bash
for s in speckit-analyze speckit-checklist speckit-clarify speckit-implement speckit-specify; do
  cp "/Users/bkohler/automation/opsmill/styrmin/.agents/skills/$s/SKILL.md" ".agents/skills/$s/SKILL.md"
done
```

- [ ] **Step 2: Verify hashes now match Phase-2 manifest**

Run: `python3 -c "import json,hashlib; m=json.load(open('.specify/integrations/claude.manifest.json')); [print(p,'OK' if hashlib.sha256(open(p,'rb').read()).hexdigest()==h else 'MISMATCH') for p,h in m['files'].items()]"`
Expected: every line ends in `OK`.

- [ ] **Step 3: Commit**

```bash
git add .agents/skills/speckit-analyze .agents/skills/speckit-checklist .agents/skills/speckit-clarify .agents/skills/speckit-implement .agents/skills/speckit-specify
git commit -m "chore(.agents): bump 5 speckit core skills to v0.8.1"
```

---

## Phase 4 — Install the `tinyspec` extension

Smallest, lowest-risk extension. Adds a lightweight single-file workflow for small tasks (skip the heavy multi-step SDD process). Three commands: `tinyspec`, `tinyspec.classify`, `tinyspec.implement`.

### Task 4.1: Copy the extension package

**Files:**
- Create: `.specify/extensions/tinyspec/` (recursive copy)

- [ ] **Step 1: Copy directory**

```bash
cp -R /Users/bkohler/automation/opsmill/styrmin/.specify/extensions/tinyspec .specify/extensions/tinyspec
```

- [ ] **Step 2: Verify the manifest is present and valid YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('.specify/extensions/tinyspec/extension.yml'))" && echo OK`
Expected: `OK`

### Task 4.2: Copy the 3 tinyspec skills

**Files:**
- Create: `.agents/skills/speckit-tinyspec-{tinyspec,classify,implement}/SKILL.md`

- [ ] **Step 1: Copy skill dirs**

```bash
for s in speckit-tinyspec-tinyspec speckit-tinyspec-classify speckit-tinyspec-implement; do
  cp -R "/Users/bkohler/automation/opsmill/styrmin/.agents/skills/$s" ".agents/skills/$s"
done
```

- [ ] **Step 2: Verify each SKILL.md has YAML frontmatter**

Run: `for s in speckit-tinyspec-tinyspec speckit-tinyspec-classify speckit-tinyspec-implement; do head -1 ".agents/skills/$s/SKILL.md" | grep -q '^---$' || echo "BAD: $s"; done`
Expected: no output

### Task 4.3: Copy the 6 tinyspec command files (3 user-facing + 3 `.agent.md` siblings)

**Files:**
- Create: `.agents/commands/speckit.tinyspec.{tinyspec,classify,implement}.md`
- Create: `.agents/commands/speckit.tinyspec.{tinyspec,classify,implement}.agent.md`

- [ ] **Step 1: Copy commands**

```bash
for f in speckit.tinyspec.tinyspec.md speckit.tinyspec.tinyspec.agent.md \
         speckit.tinyspec.classify.md speckit.tinyspec.classify.agent.md \
         speckit.tinyspec.implement.md speckit.tinyspec.implement.agent.md; do
  cp "/Users/bkohler/automation/opsmill/styrmin/.agents/commands/$f" ".agents/commands/$f"
done
```

- [ ] **Step 2: Commit**

```bash
git add .specify/extensions/tinyspec .agents/skills/speckit-tinyspec-tinyspec .agents/skills/speckit-tinyspec-classify .agents/skills/speckit-tinyspec-implement .agents/commands/speckit.tinyspec.*.md
git commit -m "feat(.specify): install tinyspec extension (lightweight single-file workflow)"
```

---

## Phase 5 — Install the `review` extension

Adds the multi-agent code-review pipeline (`speckit.review.run`) plus 6 specialised aspects: `code`, `comments`, `errors`, `simplify`, `tests`, `types`. Each aspect is both a slash command and a skill, with an `.agent.md` sibling for subagent invocation.

### Task 5.1: Copy the extension package

**Files:**
- Create: `.specify/extensions/review/` (recursive copy, includes scripts/, tests/, .github/, config-template.yml)

- [ ] **Step 1: Copy directory**

```bash
cp -R /Users/bkohler/automation/opsmill/styrmin/.specify/extensions/review .specify/extensions/review
chmod +x .specify/extensions/review/scripts/bash/*.sh
```

- [ ] **Step 2: Verify the manifest parses**

Run: `python3 -c "import yaml; m=yaml.safe_load(open('.specify/extensions/review/extension.yml')); print(m['extension']['id'])"`
Expected: `review`

### Task 5.2: Copy the 8 review skills

**Files:**
- Create: `.agents/skills/speckit-review/SKILL.md`
- Create: `.agents/skills/speckit-review-{run,code,comments,errors,simplify,tests,types}/SKILL.md`

- [ ] **Step 1: Copy skill dirs**

```bash
for s in speckit-review speckit-review-run speckit-review-code speckit-review-comments \
         speckit-review-errors speckit-review-simplify speckit-review-tests speckit-review-types; do
  cp -R "/Users/bkohler/automation/opsmill/styrmin/.agents/skills/$s" ".agents/skills/$s"
done
```

- [ ] **Step 2: Verify all 8 are present**

Run: `ls -d .agents/skills/speckit-review* | wc -l`
Expected: `8`

### Task 5.3: Copy the 14 review command files (7 user-facing + 7 `.agent.md` siblings)

**Files:**
- Create: `.agents/commands/speckit.review.md`, `speckit.review.run.md`
- Create: `.agents/commands/speckit.review.{code,comments,errors,simplify,tests,types}.md`
- Create: `.agents/commands/speckit.review.{run,code,comments,errors,simplify,tests,types}.agent.md`

- [ ] **Step 1: Copy commands**

```bash
for f in speckit.review.md speckit.review.agent.md \
         speckit.review.run.md speckit.review.run.agent.md \
         speckit.review.code.md speckit.review.code.agent.md \
         speckit.review.comments.md speckit.review.comments.agent.md \
         speckit.review.errors.md speckit.review.errors.agent.md \
         speckit.review.simplify.md speckit.review.simplify.agent.md \
         speckit.review.tests.md speckit.review.tests.agent.md \
         speckit.review.types.md speckit.review.types.agent.md; do
  cp "/Users/bkohler/automation/opsmill/styrmin/.agents/commands/$f" ".agents/commands/$f"
done
```

- [ ] **Step 2: Verify count**

Run: `ls .agents/commands/speckit.review*.md | wc -l`
Expected: `16`

- [ ] **Step 3: Commit**

```bash
git add .specify/extensions/review .agents/skills/speckit-review* .agents/commands/speckit.review*.md
git commit -m "feat(.specify): install review extension (multi-agent PR review pipeline)"
```

---

## Phase 6 — Install workflow-finishing extensions: summary, retrospect, archive, extract

These extensions cleanly close out a feature: summarise what was done, retro on it, archive the spec dir, extract knowledge into `dev/`. Each is independent, so do them in 4 small commits.

### Task 6.1: Install `summary` extension

**Files:**
- Create: `.specify/extensions/summary/`
- Create: `.agents/skills/speckit-summary-run/SKILL.md`
- Create: `.agents/commands/speckit.summary.run.md`, `.agents/commands/speckit.summary.run.agent.md`

- [ ] **Step 1: Copy package, skill, commands**

```bash
cp -R /Users/bkohler/automation/opsmill/styrmin/.specify/extensions/summary .specify/extensions/summary
cp -R /Users/bkohler/automation/opsmill/styrmin/.agents/skills/speckit-summary-run .agents/skills/speckit-summary-run
cp /Users/bkohler/automation/opsmill/styrmin/.agents/commands/speckit.summary.run.md .agents/commands/speckit.summary.run.md
cp /Users/bkohler/automation/opsmill/styrmin/.agents/commands/speckit.summary.run.agent.md .agents/commands/speckit.summary.run.agent.md
```

- [ ] **Step 2: Commit**

```bash
git add .specify/extensions/summary .agents/skills/speckit-summary-run .agents/commands/speckit.summary.run*
git commit -m "feat(.specify): install summary extension"
```

### Task 6.2: Install `retrospect` extension

**Files:**
- Create: `.specify/extensions/retrospect/`
- Create: `.agents/skills/speckit-retrospect-run/SKILL.md`
- Create: `.agents/commands/speckit.retrospect.run.md`, `.agents/commands/speckit.retrospect.run.agent.md`

- [ ] **Step 1: Copy**

```bash
cp -R /Users/bkohler/automation/opsmill/styrmin/.specify/extensions/retrospect .specify/extensions/retrospect
cp -R /Users/bkohler/automation/opsmill/styrmin/.agents/skills/speckit-retrospect-run .agents/skills/speckit-retrospect-run
cp /Users/bkohler/automation/opsmill/styrmin/.agents/commands/speckit.retrospect.run.md .agents/commands/speckit.retrospect.run.md
cp /Users/bkohler/automation/opsmill/styrmin/.agents/commands/speckit.retrospect.run.agent.md .agents/commands/speckit.retrospect.run.agent.md
```

- [ ] **Step 2: Commit**

```bash
git add .specify/extensions/retrospect .agents/skills/speckit-retrospect-run .agents/commands/speckit.retrospect.run*
git commit -m "feat(.specify): install retrospect extension"
```

### Task 6.3: Install `archive` extension

**Files:**
- Create: `.specify/extensions/archive/`
- Create: `.agents/skills/speckit-archive/SKILL.md`
- Create: `.agents/commands/speckit.archive.md`, `.agents/commands/speckit.archive.run.md`

- [ ] **Step 1: Copy**

```bash
cp -R /Users/bkohler/automation/opsmill/styrmin/.specify/extensions/archive .specify/extensions/archive
cp -R /Users/bkohler/automation/opsmill/styrmin/.agents/skills/speckit-archive .agents/skills/speckit-archive
cp /Users/bkohler/automation/opsmill/styrmin/.agents/commands/speckit.archive.md .agents/commands/speckit.archive.md
cp /Users/bkohler/automation/opsmill/styrmin/.agents/commands/speckit.archive.run.md .agents/commands/speckit.archive.run.md
```

- [ ] **Step 2: Commit**

```bash
git add .specify/extensions/archive .agents/skills/speckit-archive .agents/commands/speckit.archive*
git commit -m "feat(.specify): install archive extension"
```

### Task 6.4: Install `extract` extension as `extract.run` (preserve local `speckit.extract.md`)

**Files:**
- Create: `.specify/extensions/extract/`
- Create: `.agents/skills/speckit-extract-run/SKILL.md`
- Create: `.agents/commands/speckit.extract.run.md`, `.agents/commands/speckit.extract.run.agent.md`
- Preserve: existing `.agents/commands/speckit.extract.md` (local infrahub-mcp variant)

- [ ] **Step 1: Confirm local `speckit.extract.md` is the project-tuned variant (not the styrmin one)**

Run: `head -2 .agents/commands/speckit.extract.md`
Expected: `description: Extract ADRs, knowledge, and guidelines from completed specifications into dev/ documentation.`
(If output instead matches styrmin's wording, abort and check with user — the file got clobbered earlier.)

- [ ] **Step 2: Copy the extension package and the `.run` command/skill (different names; no collision)**

```bash
cp -R /Users/bkohler/automation/opsmill/styrmin/.specify/extensions/extract .specify/extensions/extract
cp -R /Users/bkohler/automation/opsmill/styrmin/.agents/skills/speckit-extract-run .agents/skills/speckit-extract-run
cp /Users/bkohler/automation/opsmill/styrmin/.agents/commands/speckit.extract.run.md .agents/commands/speckit.extract.run.md
cp /Users/bkohler/automation/opsmill/styrmin/.agents/commands/speckit.extract.run.agent.md .agents/commands/speckit.extract.run.agent.md
```

- [ ] **Step 3: Verify both extract commands coexist**

Run: `ls .agents/commands/speckit.extract*.md`
Expected: `speckit.extract.md  speckit.extract.run.agent.md  speckit.extract.run.md`

- [ ] **Step 4: Commit**

```bash
git add .specify/extensions/extract .agents/skills/speckit-extract-run .agents/commands/speckit.extract.run*
git commit -m "feat(.specify): install extract extension as speckit.extract.run; keep local speckit.extract"
```

---

## Phase 7 — Install advanced workflow extensions: iterate, reconcile, critique, checkpoint, auto

These add iteration loops, reconciliation, critique passes, mid-flight checkpoints, and full-pipeline auto-runs. Lower-priority than Phases 4–6, but listed for parity. Independent commits per extension so the user can stop after any of them if they decide some aren't worth carrying.

### Task 7.1: Install `iterate` extension (2 commands: define + apply)

**Files:**
- Create: `.specify/extensions/iterate/`
- Create: `.agents/skills/speckit-iterate-{define,apply}/SKILL.md`
- Create: `.agents/commands/speckit.iterate.{define,apply}.md`

- [ ] **Step 1: Copy**

```bash
cp -R /Users/bkohler/automation/opsmill/styrmin/.specify/extensions/iterate .specify/extensions/iterate
cp -R /Users/bkohler/automation/opsmill/styrmin/.agents/skills/speckit-iterate-define .agents/skills/speckit-iterate-define
cp -R /Users/bkohler/automation/opsmill/styrmin/.agents/skills/speckit-iterate-apply .agents/skills/speckit-iterate-apply
cp /Users/bkohler/automation/opsmill/styrmin/.agents/commands/speckit.iterate.define.md .agents/commands/speckit.iterate.define.md
cp /Users/bkohler/automation/opsmill/styrmin/.agents/commands/speckit.iterate.apply.md .agents/commands/speckit.iterate.apply.md
```

- [ ] **Step 2: Commit**

```bash
git add .specify/extensions/iterate .agents/skills/speckit-iterate-* .agents/commands/speckit.iterate.*.md
git commit -m "feat(.specify): install iterate extension"
```

### Task 7.2: Install `reconcile` extension

**Files:**
- Create: `.specify/extensions/reconcile/`, `.agents/skills/speckit-reconcile-run/`, `.agents/commands/speckit.reconcile.run.md`

- [ ] **Step 1: Copy**

```bash
cp -R /Users/bkohler/automation/opsmill/styrmin/.specify/extensions/reconcile .specify/extensions/reconcile
cp -R /Users/bkohler/automation/opsmill/styrmin/.agents/skills/speckit-reconcile-run .agents/skills/speckit-reconcile-run
cp /Users/bkohler/automation/opsmill/styrmin/.agents/commands/speckit.reconcile.run.md .agents/commands/speckit.reconcile.run.md
```

- [ ] **Step 2: Commit**

```bash
git add .specify/extensions/reconcile .agents/skills/speckit-reconcile-run .agents/commands/speckit.reconcile.run.md
git commit -m "feat(.specify): install reconcile extension"
```

### Task 7.3: Install `critique` extension

**Files:**
- Create: `.specify/extensions/critique/`, `.agents/skills/speckit-critique-run/`, `.agents/commands/speckit.critique.run.md`

- [ ] **Step 1: Copy**

```bash
cp -R /Users/bkohler/automation/opsmill/styrmin/.specify/extensions/critique .specify/extensions/critique
cp -R /Users/bkohler/automation/opsmill/styrmin/.agents/skills/speckit-critique-run .agents/skills/speckit-critique-run
cp /Users/bkohler/automation/opsmill/styrmin/.agents/commands/speckit.critique.run.md .agents/commands/speckit.critique.run.md
```

- [ ] **Step 2: Commit**

```bash
git add .specify/extensions/critique .agents/skills/speckit-critique-run .agents/commands/speckit.critique.run.md
git commit -m "feat(.specify): install critique extension"
```

### Task 7.4: Install `checkpoint` extension

**Files:**
- Create: `.specify/extensions/checkpoint/`, `.agents/skills/speckit-checkpoint-commit/`, `.agents/commands/speckit.checkpoint.commit.md` (+ `.agent.md`)

- [ ] **Step 1: Copy**

```bash
cp -R /Users/bkohler/automation/opsmill/styrmin/.specify/extensions/checkpoint .specify/extensions/checkpoint
cp -R /Users/bkohler/automation/opsmill/styrmin/.agents/skills/speckit-checkpoint-commit .agents/skills/speckit-checkpoint-commit
cp /Users/bkohler/automation/opsmill/styrmin/.agents/commands/speckit.checkpoint.commit.md .agents/commands/speckit.checkpoint.commit.md
cp /Users/bkohler/automation/opsmill/styrmin/.agents/commands/speckit.checkpoint.commit.agent.md .agents/commands/speckit.checkpoint.commit.agent.md
```

- [ ] **Step 2: Commit**

```bash
git add .specify/extensions/checkpoint .agents/skills/speckit-checkpoint-commit .agents/commands/speckit.checkpoint.commit*
git commit -m "feat(.specify): install checkpoint extension"
```

### Task 7.5: Install `auto` extension (full pipeline runner)

**Files:**
- Create: `.specify/extensions/auto/`, `.agents/skills/speckit-auto-run/`, `.agents/commands/speckit.auto.run.md` (+ `.agent.md`)

- [ ] **Step 1: Copy**

```bash
cp -R /Users/bkohler/automation/opsmill/styrmin/.specify/extensions/auto .specify/extensions/auto
cp -R /Users/bkohler/automation/opsmill/styrmin/.agents/skills/speckit-auto-run .agents/skills/speckit-auto-run
cp /Users/bkohler/automation/opsmill/styrmin/.agents/commands/speckit.auto.run.md .agents/commands/speckit.auto.run.md
cp /Users/bkohler/automation/opsmill/styrmin/.agents/commands/speckit.auto.run.agent.md .agents/commands/speckit.auto.run.agent.md
```

- [ ] **Step 2: Commit**

```bash
git add .specify/extensions/auto .agents/skills/speckit-auto-run .agents/commands/speckit.auto.run*
git commit -m "feat(.specify): install auto extension (full-pipeline runner)"
```

### Task 7.6: Generate the `.specify/extensions/.registry`

**Files:**
- Create: `.specify/extensions/.registry`

The registry tracks which extensions are installed and which commands they registered with each AI agent. Copy styrmin's and prune any local entries that don't apply.

- [ ] **Step 1: Copy registry**

```bash
cp /Users/bkohler/automation/opsmill/styrmin/.specify/extensions/.registry .specify/extensions/.registry
```

- [ ] **Step 2: Verify the JSON parses**

Run: `python3 -c "import json; r=json.load(open('.specify/extensions/.registry')); print(sorted(r['extensions'].keys()))"`
Expected: `['archive', 'auto', 'checkpoint', 'critique', 'extract', 'git', 'iterate', 'reconcile', 'retrospect', 'review', 'summary', 'tinyspec']`

- [ ] **Step 3: Commit**

```bash
git add .specify/extensions/.registry
git commit -m "chore(.specify): record installed extensions in .registry"
```

---

## Phase 8 — Wire up the extension hook chain in `extensions.yml`

The current `extensions.yml` only declares git hooks. Now that 11 more extensions are installed, replace it with styrmin's hook chain (auto-commits before each speckit phase + tinyspec classification before specify + review.run after implement).

### Task 8.1: Replace `.specify/extensions.yml`

**Files:**
- Overwrite: `.specify/extensions.yml`

- [ ] **Step 1: Diff the two files first to surface any project-specific edits in the current copy**

Run: `diff .specify/extensions.yml /Users/bkohler/automation/opsmill/styrmin/.specify/extensions.yml`
Expected: differences in hook ordering and the addition of tinyspec/review hooks. If you see anything that looks infrahub-mcp-specific (e.g., a custom hook the user added), STOP and check with user.

- [ ] **Step 2: Copy styrmin's extensions.yml**

```bash
cp /Users/bkohler/automation/opsmill/styrmin/.specify/extensions.yml .specify/extensions.yml
```

- [ ] **Step 3: Validate YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('.specify/extensions.yml'))" && echo OK`
Expected: `OK`

- [ ] **Step 4: Verify all referenced extensions actually exist on disk**

Run:
```bash
python3 - <<'EOF'
import yaml, os, sys
cfg = yaml.safe_load(open('.specify/extensions.yml'))
missing = []
for hook_name, entries in (cfg.get('hooks') or {}).items():
    for e in entries:
        ext_dir = f".specify/extensions/{e['extension']}"
        if not os.path.isdir(ext_dir):
            missing.append((hook_name, e['extension']))
print("MISSING:", missing) if missing else print("OK")
EOF
```
Expected: `OK`. If `MISSING`, the listed extension directories were not installed in earlier phases.

- [ ] **Step 5: Commit**

```bash
git add .specify/extensions.yml
git commit -m "feat(.specify): wire extension hook chain (tinyspec classify, review.run, auto-commits)"
```

---

## Phase 9 — Verification + final commit

### Task 9.1: Final structural smoke test

**Files:**
- None modified

- [ ] **Step 1: Skill ↔ command parity check (every skill has a matching command, every command has a matching skill)**

Run:
```bash
python3 - <<'EOF'
import os
skills = {d for d in os.listdir('.agents/skills') if os.path.isdir(os.path.join('.agents/skills', d)) and d.startswith('speckit-')}
cmds_user = {f.replace('.md','').replace('.','-') for f in os.listdir('.agents/commands') if f.startswith('speckit.') and not f.endswith('.agent.md')}
# normalize: speckit.review.code.md -> speckit-review-code, matches skill speckit-review-code
only_skill = skills - cmds_user
only_cmd = cmds_user - skills
print("SKILL without USER COMMAND:", sorted(only_skill))
print("USER COMMAND without SKILL:", sorted(only_cmd))
EOF
```
Expected: both lists are either empty or contain only known intentional asymmetries (e.g., `speckit.extract` is project-local with no skill counterpart). If anything else appears, surface it before continuing.

- [ ] **Step 2: Frontmatter sanity — every command and SKILL.md starts with `---`**

Run:
```bash
bad=$(find .agents/commands .agents/skills -name '*.md' -exec sh -c 'head -1 "$1" | grep -q "^---$" || echo "$1"' _ {} \;)
[ -z "$bad" ] && echo OK || echo "BAD: $bad"
```
Expected: `OK`

- [ ] **Step 3: Lint the YAML files we touched**

Run: `uv run invoke lint-yaml`
Expected: passes. If yamllint flags any of the new manifests, fix the specific complaint (don't suppress globally) and re-run.

- [ ] **Step 4: Run pre-commit + pytest before pushing**

Run: `uv sync && uv run pre-commit run --all-files && uv run pytest`
Expected: green. The speckit changes are all in `.specify/` and `.agents/`, neither of which is touched by the Python pipeline, so no test regressions are expected. If something fails, the failure is unrelated to this plan — surface it before pushing.

### Task 9.2: Document the bump in the project memory

**Files:**
- Modify: `.agents/skills/README.md` (only if a "Skills index" section exists; otherwise skip)

- [ ] **Step 1: Decide whether the existing README needs an updated extension list**

Run: `grep -n -E "extension|tinyspec|review|summary" .agents/skills/README.md || echo "no extension index — nothing to update"`
Expected: either the README has an explicit extension/skill list (in which case update it to include the new skills) or the message `no extension index — nothing to update` (in which case skip this task).

- [ ] **Step 2: If updating, append the new skills to the index, alphabetically sorted, then commit**

```bash
git add .agents/skills/README.md
git commit -m "docs(.agents): index newly installed speckit extension skills"
```

### Task 9.3: Final summary commit (if anything left over)

- [ ] **Step 1: Confirm working tree is clean**

Run: `git status --short`
Expected: empty

- [ ] **Step 2: Show the bump diff against `origin/stable` for the user to review before pushing**

Run: `git log --oneline origin/stable..HEAD`
Expected: a chain of commits from Phases 1–9. STOP before pushing — the user explicitly requires feature-branch workflow per their feedback memory `feedback_branch_workflow.md`. This plan's commits should land on `feat/speckit-0.8.1-sync` (or similar), not on `stable`.

---

## Self-Review Notes

- **Spec coverage:** Every diff item identified in the inventory phase has a task: 14 missing commands (Phase 1), 5 stale skills (Phase 3), 11 missing extensions × {extension dir, skills, commands} (Phases 4–7), version metadata (Phase 2), hook chain (Phase 8), verification (Phase 9).
- **No placeholders:** Every `cp` command names the exact source and destination paths; every verification step has an exact expected result.
- **Type consistency:** Skill directory names use `kebab-case` (`speckit-review-run`); slash-command file names use dot-case (`speckit.review.run.md`); extension IDs use `kebab-case` (`review`, `tinyspec`). The mapping is consistent across phases.
- **Branch safety:** Per the user's feedback memory, this plan's commits MUST land on a feature branch, not `stable`. Phase 9 Task 3 Step 2 is the gate that catches this.
- **Reversibility:** Every phase commits independently. If a later phase breaks something, `git revert` of just that phase's commits is enough to recover. No phase clobbers project-owned files (`constitution.md`, `adr-template.md`, `init-options.json` `branch_numbering`).
