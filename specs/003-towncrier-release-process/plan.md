# Implementation Plan: Towncrier-based release process

**Branch**: `003-towncrier-release-process` | **Date**: 2026-09-10 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-towncrier-release-process/spec.md`

## Summary

towncrier is already configured here but nothing runs it. Wire it up: require a news fragment on every pull request, assemble `CHANGELOG.md` at release time, and deliver the version bump plus the assembled changelog as a reviewable `chore(release)` pull request whose merge tags and publishes the release. Retire `release-drafter`.

This repository is the **pilot** for the same change in infrahub-skills and infrahub-ansible.

## Technical Context

**Language/Version**: Python 3.13 via `uv`; workflows are GitHub Actions YAML and bash.

**Primary Dependencies**: `towncrier` (already in the dev group); `patrickjahns/version-drafter-action@v1.3.1` (existing, retained); `gh` CLI.

**Storage**: Files only — fragments in `changelog/`, assembled output in `CHANGELOG.md`.

**Testing**: No unit tests — the feature adds no importable code. Verification is exercising `towncrier build` and the release-body extraction locally, plus `yamllint`/`rumdl` in CI. The release workflows cannot be exercised before merge; they only trigger on `stable`.

**Target Platform**: GitHub Actions (`ubuntu-latest`).

**Project Type**: MCP server, published to PyPI and the MCP registry.

**Constraints**:

- The long-lived branch is **`stable`**, not `main`. Tags are `v`-prefixed.
- The version is authored in `pyproject.toml` and `server.json` (twice — top level and `packages[0]`), reconciled by `scripts/sync-versions.sh`.
- `CAPABILITIES.md` is **generated and version-carrying** — its heading is `## Infrahub MCP Server <version>`, which `mcp-discovery` reads from the server's `version("infrahub-mcp")`. `scripts/sync-versions.sh` does not edit it; it takes the new version when `scripts/update-capabilities.sh` regenerates it, so regeneration must run after the sync and land in the same release commit. `ci-mcp-discovery.yml` validates it by regenerating and diffing.
- Version computation must stay isolated in one step emitting only a version string, so a later migration onto the shared `release-prepare` can consume it as `bump-strategy: manual` + `version:`.
- `version-sync.yml` chains off the `Auto bump version` workflow by name via `workflow_run`; renaming that workflow would silently break it.

**Scale/Scope**: 3 workflow files, 1 deleted config, the seeded `CHANGELOG.md`, and `AGENTS.md`.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-checked after Phase 1 design.*

`.specify/memory/constitution.md` exists in this repo and governs server/plugin concerns. This feature touches no server code, no middleware, no auth, and no schema — it is confined to CI, packaging metadata and documentation.

**Ask First gates** (from `AGENTS.md`): none are crossed.

| Gate | Crossed? |
| --- | --- |
| Adding new dependencies | No — towncrier is already a dev dependency |
| Changing authentication behavior | No |
| Modifying the middleware stack order | No |
| Schema or API contract changes | No |

The **Never Do** entry "Force push to `stable`" is respected: the release path adds a reviewed pull request and never writes to `stable` directly. The bot force-pushes only its own regenerated `release/*` branch.

**Result: PASS.** Complexity Tracking is empty.

## Project Structure

### Documentation (this feature)

```text
specs/003-towncrier-release-process/
├── spec.md
├── plan.md              # This file
└── tasks.md
```

`research.md`, `data-model.md`, `contracts/` and `quickstart.md` are **not** generated: no unknowns to research (decisions are recorded in the spec's Assumptions), no data entities beyond files, and no change to the server's exposed contract.

### Source Code (repository root)

```text
.github/
├── release-drafter.yml              # DELETED
└── workflows/
    ├── changelog-check.yml          # NEW  — PR-time fragment gate
    ├── release-publish.yml          # NEW  — tag + publish on release-PR merge
    └── auto-bump.yml                # EDIT — assemble changelog, open release PR,
                                     #        drop the release-drafter job.
                                     #        Workflow NAME is unchanged, because
                                     #        version-sync.yml keys on it.

CHANGELOG.md                         # NEW  — seeded with the towncrier marker
AGENTS.md                            # EDIT — Changelog section
```

**Structure Decision**: No source-tree option applies; this feature touches no `src/`. The layout above is the real set of paths changed.

## Complexity Tracking

> No Constitution Check violations. Table intentionally empty.
