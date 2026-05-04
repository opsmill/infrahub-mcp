# Feature completion checklist

This guideline captures the post-implementation steps that are easy to miss locally but enforced by CI. Run through the relevant sections before pushing a feature branch — if you skip them, CI will catch the omission, but waiting for CI to find drift is wasteful.

The companion local command is:

```bash
uv run invoke format ci
```

`invoke ci` runs every CI gate locally (lint, repo-state validation, documentation style, tests). A clean local run predicts a clean CI run.

---

## New `ServerConfig` field

Adding a new `INFRAHUB_MCP_*` environment variable touches four files plus the user-facing docs. Forgetting any one of them produces a CI failure with a different signature, so the order below matches the dependency order:

1. **`src/infrahub_mcp/config.py`** — add the field on the `ServerConfig` pydantic model with a sensible default and a docstring entry. Pydantic-settings derives the env-var name from the field name (`INFRAHUB_MCP_<UPPERCASE>`). Constraints (`Field(..., ge=0, le=...)`) belong here.
2. **`server.json`** — add an entry in `packages[0].environmentVariables` so MCP registries surface the variable. The `invoke validate-serverjson` task (run by CI) flags missing or stale entries; `--update` regenerates them automatically.
3. **`docker-compose.yml`** — add the variable to the `x-infrahub-mcp-config` anchor. The list **must be sorted alphabetically** because `invoke validate-dockercomposeenv` regenerates and diffs against the committed file. Run `invoke gen-config-env --update` to apply the canonical sort, or hand-edit and re-sort.
4. **`development/docker-compose.yml`** — same shape as `docker-compose.yml`. Not validated by CI but kept in sync by convention so dev-mode operators get the same defaults.
5. **`docs/docs/references/configuration.mdx`** — describe the variable with its default and behavioural impact. Place it in the section that matches the feature area; do not bury it under an unrelated heading.

Local verification:

```bash
uv run invoke validate    # validate-dockercomposeenv + validate-serverjson
uv run invoke lint-vale   # documentation style
```

`invoke validate-serverjson --update` and `invoke gen-config-env --update` are both available for auto-fix; CI runs them in validate-only mode.

### Why this is fragile

The four locations exist for legitimate reasons (typed runtime config, MCP registry metadata, deployment defaults, user documentation), but the validators only catch *omissions* — they cannot tell you the docs paragraph is misleading or that the docker-compose default is wrong for a passthrough deployment. Treat the docs entry as load-bearing, not as a checkbox.

---

## Spec lifecycle

Features scaffolded under `specs/` (via `/speckit-specify`) follow this lifecycle:

```
specs/<timestamp>-<name>/    →    dev/adr/<NNNN>-<name>.md  +  specs/archive/<timestamp>-<name>/
   (work-in-progress)             (durable architectural        (frozen historical record)
                                   decisions)
```

After the implementation lands and tests are green, do the following before merging the PR:

1. **Extract an ADR** under `dev/adr/<NNNN>-<short-name>.md` using the existing template (see ADRs 0001–0007). The ADR captures *why* — the load-bearing decisions, the alternatives considered, the constraints. It does **not** repeat the spec's user-story narrative or implementation details.
2. **Move the spec to `specs/archive/`**. Use `git mv specs/<timestamp>-<name>/ specs/archive/<timestamp>-<name>/`. Update any cross-references (the new ADR, AGENTS.md SPECKIT pointer if it referenced the spec) to the new path.
3. **Drop `.specify/feature.json`** so the next `/speckit-specify` session starts clean.
4. **Reset the AGENTS.md SPECKIT pointer** to its generic placeholder (the bare instruction sentence between `<!-- SPECKIT START -->` and `<!-- SPECKIT END -->`).

Precedent: ADR 0007 (`hash-validated schema cache`) was extracted from `specs/archive/20260504-203256-schema-cache/`; ADR-extraction-then-archival pattern was established by INFP-411 (`specs/archive/20260421-144953-production-ready-mcp-server/`).

### What goes in the ADR vs the spec

- **Spec** answers: *what does this feature do, and why does the user need it?*
- **ADR** answers: *why did we pick this implementation shape over the alternatives, and what should a future contributor reading the code recognise as load-bearing?*

When in doubt, ask whether the statement will still be informative in 12 months. Spec text rots with the feature; ADR text records the reasoning that made the design defensible at the time.

---

## Pre-push checklist

Run before any `git push` on a feature branch:

```bash
uv run invoke format ci
```

If `invoke ci` fails on a check that you don't recognise, treat that as a signal to update either:

- This guideline (if the gate is new and undocumented), or
- `tasks.py` (if `invoke ci` doesn't actually mirror the CI gate that fired).

The goal is symmetry: every CI failure should be locally reproducible, and every fix you ship should reach CI through a green local pipeline first.

### Speckit branch-naming friction

`speckit-specify` and the `.specify/scripts/bash/check-prerequisites.sh` validator currently disagree on branch naming: the skill accepts a `GIT_BRANCH_NAME` override (we use the project's `feat/<name>` convention), but the validator only accepts `<num>-<name>` or `<timestamp>-<name>`. Until that's fixed upstream, work around it by:

- Running `speckit-git-feature` with `GIT_BRANCH_NAME=feat/<name>` to create the branch.
- Resolving `FEATURE_DIR` and `FEATURE_SPEC` paths manually (they're under `specs/<timestamp>-<short-name>/`) instead of relying on `check-prerequisites.sh`.
- Skipping `setup-plan.sh`'s branch validator and copying `.specify/templates/plan-template.md` directly when running `/speckit-plan`.
