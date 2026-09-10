# Feature Specification: Towncrier-based release process

**Feature Branch**: `003-towncrier-release-process`  
**Created**: 2026-09-10  
**Status**: Draft  
**Input**: User description: "Replace the release-drafter based release process with a towncrier-managed changelog, label-driven version bumping, and a reviewable release PR, shaped to match the opsmill-cicd-workflows release-prepare contract for later migration."

## Context

This repository already has towncrier configured correctly — `changelog/` with the seven standard OpsMill types, the canonical template, and a fragment pending (`147.added.md`). What is missing is the other half: nothing ever runs `towncrier build`, so no `CHANGELOG.md` exists and no fragment has ever reached a reader.

Release notes today come from `release-drafter`, which lists PR titles. So contributors write fragments that go nowhere, while users read titles nobody wrote for them. This feature connects the two ends.

**This repository is the pilot** for a three-repo adoption (infrahub-mcp, then infrahub-skills, then infrahub-ansible). It was chosen because towncrier is already in place and the repo is the simplest case — a single long-lived branch (`stable`), `v`-prefixed tags, and an existing `scripts/sync-versions.sh`. The pattern proven here is what the other two follow.

All three implement locally but are deliberately shaped to match the `opsmill-cicd-workflows` `release-prepare` contract, so a later migration owned by SRE is workflow rewiring rather than redesign.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A contributor's own words reach the release (Priority: P1)

A contributor changes behaviour and records that change in one line, in the same pull request. When the release ships, their line appears in the release notes.

**Why this priority**: Fragments are already being written and are currently discarded. This is the smallest change that makes the existing practice count for something.

**Independent Test**: Merge a PR carrying a fragment, cut a release, confirm the line appears verbatim in the published release body. Delivers a truthful changelog even if nothing else here is built.

**Acceptance Scenarios**:

1. **Given** a contributor opens a PR changing behaviour, **When** they merge it with no newsfragment and no `ci/skip-changelog` label, **Then** the PR check fails and names the fragment path to create.
2. **Given** the contributor adds `changelog/<id>.<type>.md` and merges, **When** the next release is published, **Then** the release body contains that line under its category heading.
3. **Given** a trivial PR labelled `ci/skip-changelog`, **When** it is merged with no fragment, **Then** the check passes.
4. **Given** the existing pending fragment `147.added.md`, **When** the first release under this process is cut, **Then** it appears in `CHANGELOG.md` rather than being lost.

---

### User Story 2 - Maintainer cuts a release from a reviewable PR (Priority: P2)

A maintainer promotes accumulated work. The version is computed from PR labels, `CHANGELOG.md` is assembled from fragments, and both arrive as a reviewable pull request rather than as a push side effect.

**Why this priority**: Delivers the auditable release path and retires `release-drafter`, but User Story 1 already delivers a correct changelog without it.

**Independent Test**: Trigger release preparation, confirm a `chore(release): vX.Y.Z` PR appears containing only version files and the assembled changelog section, and that publishing cannot happen until it merges.

**Acceptance Scenarios**:

1. **Given** merged PRs labelled `changes/minor`, **When** release preparation runs, **Then** the computed version is the correct minor bump, emitted as a single version string from a discrete step.
2. **Given** fragments exist in `changelog/`, **When** the release PR is built, **Then** `pyproject.toml`, `server.json` and `CAPABILITIES.md` carry the new version and `CHANGELOG.md` gains the assembled section.
3. **Given** no fragments exist, **When** release preparation runs, **Then** it fails rather than producing an empty changelog section.
4. **Given** the release PR is merged and the GitHub release published, **Then** the release body is the towncrier-rendered section.

---

### User Story 3 - Curated notes for a notable release (Priority: P3)

For a release worth explaining, a maintainer produces a workflow-first prose page from the assembled changelog, published to the docs site.

**Why this priority**: Optional by design. `CHANGELOG.md` covers every release; this covers releases where a human has something to teach. Mandating it is how the practice decays.

**Independent Test**: Take a published release's changelog section, run the release-notes skill against it, confirm a docs page renders in the site build.

**Acceptance Scenarios**:

1. **Given** a published minor release, **When** the release-notes skill runs with the towncrier output as input, **Then** a release-notes page is produced and renders in the docs build.

---

### Edge Cases

- **Dependabot and bot PRs** cannot write fragments — they are auto-labelled `ci/skip-changelog`.
- **A release where every PR was skip-labelled** yields zero fragments: preparation hard-fails and the releaser adds a housekeeping fragment. There is no empty-release opt-out, matching the platform's per-release rule.
- **Two PRs choosing the same fragment slug** collide as an ordinary file conflict, resolved in git.
- **The first build has no `CHANGELOG.md`** — towncrier creates it. The file must gain the `<!-- towncrier release notes start -->` marker so subsequent builds insert rather than overwrite.
- **`update-capabilities.sh` rewrites `CAPABILITIES.md`** during the bump; the release PR must include that regeneration rather than leaving it to a follow-up commit.
- **Three version files** (`pyproject.toml`, `server.json`, `CAPABILITIES.md`) must move together via `sync-versions.sh`.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST fail a pull-request check when the PR adds no newsfragment and carries no `ci/skip-changelog` label.
- **FR-002**: System MUST compute the next version from PR labels (`changes/*`, `type/*`) and expose it as a single version string produced by a discrete step.
- **FR-003**: System MUST assemble `CHANGELOG.md` from newsfragments using towncrier at release time, and MUST fail rather than emit an empty section.
- **FR-004**: System MUST use the towncrier-rendered section as the GitHub Release body.
- **FR-005**: System MUST keep the two versioned files — `pyproject.toml` and `server.json` (both its top-level `version` and `packages[0].version`) — in step via `scripts/sync-versions.sh`.
- **FR-005a**: System MUST regenerate `CAPABILITIES.md` in the release commit via `scripts/update-capabilities.sh`. `CAPABILITIES.md` carries **no version string** — it is a generated capability listing that `ci-mcp-discovery.yml` validates by regenerating and diffing — so the requirement is that it is current, not that it matches a version.
- **FR-006**: System MUST create `CHANGELOG.md` with the towncrier start marker on first build.
- **FR-007**: Users MUST be able to skip the fragment requirement on a trivial PR via `ci/skip-changelog`.
- **FR-008**: Release changes MUST arrive as a reviewable pull request that requires approval before a tag is created.
- **FR-009**: System MUST NOT retain `release-drafter` — its configuration and workflow wiring are removed.
- **FR-010**: Version computation MUST remain separable from the release job, so it can later be wired into `release-prepare` as `bump-strategy: manual` with an explicit `version:` input.
- **FR-011**: The existing pending fragment MUST be carried into the first release rather than discarded.

### Key Entities

- **Newsfragment**: `changelog/<id>.<type>.md`; one per change, one line of Markdown. Already established here.
- **CHANGELOG.md**: the assembled canonical record; does not yet exist, created by the first build.
- **Release PR**: `chore(release): vX.Y.Z`; carries version files plus the assembled changelog section and is the approval point.
- **GitHub Release body**: the towncrier-rendered section; replaces the release-drafter PR-title list.
- **Version string**: label-derived; written to `pyproject.toml` and `server.json`, and used as the `v`-prefixed git tag.
- **Curated release-notes page**: optional prose page on the docs site, generated from the changelog section.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of releases published after adoption carry at least one human-written changelog entry.
- **SC-002**: Zero fragments are discarded — every fragment merged reaches exactly one published release.
- **SC-003**: Zero changelog merge conflicts across all pull requests in the first two release cycles.
- **SC-004**: No release requires a changelog commit after publication — notes are complete at publish time.
- **SC-005**: `pyproject.toml` and `server.json` report the same version at every tagged commit, and `CAPABILITIES.md` matches what `update-capabilities.sh` regenerates at that commit.
- **SC-006**: A later migration onto the shared workflows changes only workflow wiring — zero edits to fragment content, fragment directory, or category taxonomy.

## Governance Gates Crossed

Per this repository's `AGENTS.md` **Ask First** list — none are crossed:

- [ ] Adding new dependencies — towncrier is already a dev dependency here.
- [ ] Changing authentication behavior — not touched.
- [ ] Modifying the middleware stack order — not touched.
- [ ] Schema or API contract changes — not touched.

Note that unlike the sibling ansible collection, this repository does not gate CI workflow changes behind Ask First. The **Never Do** entry "Force push to `stable`" is respected: the release path adds a reviewed PR rather than any direct or forced write.

## Assumptions

- PR labels are applied reliably; conventional-commit type prefixes are **not** trustworthy across these repos, which is why the bump stays label-driven rather than adopting the platform's commit-driven `auto-semver`.
- The single `stable` branch model is retained — no `develop` branch is introduced.
- Being the pilot, decisions taken here set the pattern for infrahub-skills and infrahub-ansible; divergence in those repos should be justified by a repo-specific constraint.
- SRE owns the eventual migration onto the shared reusable workflows, on their own timeline.
- The `opsmill-cicd-workflows` `changelog-towncrier` composite currently hard-codes a `changes/` directory and will need to honour towncrier's configured `directory` before migration; this is tracked separately against that repository.

## Out of Scope

- Migrating onto the shared reusable workflows in `opsmill-cicd-workflows`.
- Changing the towncrier configuration itself — it is already compliant.
- Introducing a `develop` branch.
- Unifying conventional-commit types with towncrier fragment types — they answer different questions and both remain.
