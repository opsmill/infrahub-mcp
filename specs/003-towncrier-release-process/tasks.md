---
description: "Task list for the towncrier-based release process"
---

# Tasks: Towncrier-based release process

**Input**: Design documents from `/specs/003-towncrier-release-process/`

**Prerequisites**: [spec.md](./spec.md), [plan.md](./plan.md)

**Tests**: No test tasks. The feature adds no importable code. Verification is by exercising the tooling against real fragments plus the existing lint jobs — see Phase 4.

**Organization**: Grouped by the user stories in spec.md.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story the task serves

## Phase 1: Foundational (Blocking Prerequisites)

**Purpose**: Give towncrier somewhere to write. Blocks the release path — without a marker, `towncrier build` has no insertion point.

- [x] T001 Create `CHANGELOG.md` with the `<!-- towncrier release notes start -->` marker, matching the house header used by `opsmill/infrahub` and the SDK.

> towncrier config, `changelog/.gitignore` and the template already exist in this repository — no setup phase is needed, which is why this repo was chosen as the pilot.

---

## Phase 2: User Story 1 — A contributor's own words reach the release (P1)

**Goal**: A pull request that changes behaviour cannot merge without a news fragment.

**Independent test**: Open a PR with no fragment → the check fails; add one → it passes; label `ci/skip-changelog` with no fragment → it passes.

- [x] T002 [US1] Add `.github/workflows/changelog-check.yml`, failing a pull request that adds no file under `changelog/` unless it carries `ci/skip-changelog`. Query the API via `gh pr view --json files` rather than diffing locally, so the result does not depend on checkout depth.
- [x] T003 [US1] Make the failure message actionable — name the `towncrier create` command, the seven types, and the escape-hatch label.

**Checkpoint**: US1 delivers a correct changelog on its own.

---

## Phase 3: User Story 2 — Maintainer cuts a release from a reviewable PR (P2)

**Goal**: The version bump and assembled changelog arrive as a pull request; merging it publishes the release.

**Independent test**: Push to `stable` → a `chore(release): vX.Y.Z` PR appears containing only version files and the changelog section; publishing is impossible until it merges.

- [x] T004 [US2] Keep version computation in `auto-bump.yml` in its own step whose only output is a version string (the seam for `release-prepare`'s `bump-strategy: manual`).
- [x] T005 [US2] Add a changelog-assembly step that hard-fails when `changelog/` holds no fragments, then runs `towncrier build --version "$VERSION" --yes`.
- [x] T006 [US2] Replace the direct `stable` push with a step that creates `release/v<version>`, commits `pyproject.toml`, `server.json`, `uv.lock`, `CAPABILITIES.md`, `CHANGELOG.md` and the consumed `changelog/`, and opens the release pull request. Re-running refreshes the same branch instead of opening a second PR.
- [x] T007 [US2] Preserve the `CAPABILITIES.md` regeneration in the release commit, ordered after `sync-versions.sh`, so the regenerated file carries the new version and `ci-mcp-discovery.yml`'s diff check does not fail on the release PR.
- [x] T008 [US2] Add `.github/workflows/release-publish.yml`, tagging and publishing on merge with the assembled section as the body. Key the decision off *"does a tag exist for the version in `pyproject.toml`?"* rather than the commit message, so squash, rebase and merge behave identically.
- [x] T009 [US2] Guard the extracted body: fail if empty, and fail if it does not mention the version being released.
- [x] T010 [US2] Remove `release-drafter` — delete `.github/release-drafter.yml` and the `release-draft` job.
- [x] T011 [US2] Leave the `Auto bump version` workflow **name** unchanged so `version-sync.yml`'s `workflow_run` trigger keeps matching.

**Checkpoint**: Releases are auditable; the PyPI/registry publish path is unchanged.

---

## Phase 4: Verification

- [x] T012 Exercise `towncrier build --version 1.1.9`; confirm it assembles the pending `147.added.md` and this change's fragment under the right headings.
- [x] T013 Exercise the release-body extraction; confirm it returns exactly the new section and that the version guard trips when it should.
- [x] T014 Revert the simulation so no assembled changelog or consumed fragment is committed.
- [x] T015 [P] `yamllint` across `.github/workflows/`.
- [x] T016 [P] `rumdl` across changed Markdown.
- [ ] T017 **Cannot be done pre-merge**: `auto-bump.yml` and `release-publish.yml` only trigger on `stable`, so the release path gets its first real exercise on the next release. Watch that run.

---

## Phase 5: Documentation

- [x] T018 Add a Changelog section to `AGENTS.md` covering fragment creation, the seven types, the skip label, and the rule that versions are never bumped directly on `stable`.
- [x] T019 Add a news fragment for this change itself, exercising the workflow it introduces.

---

## Dependencies

- **T001 → Phase 3**: the marker must exist before `towncrier build` can insert.
- **Phase 2 is independent of Phase 3**: US1 ships value alone.
- **T010 → T018**: removing release-drafter makes any doc describing it wrong.

## Deferred

- **US3 (curated release notes)** is not implemented. `CHANGELOG.md` covers every release; the curated prose page is optional and applies to notable releases only.
