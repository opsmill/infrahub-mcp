# spec-kit-retrospect

A [spec-kit](https://github.com/github/spec-kit) extension that runs a session retrospective and turns agent friction into reviewed follow-up actions for repository context management.

## What Problem Does This Solve?

Agent sessions often uncover missing instructions, stale docs, weak templates, or architecture friction while the full session history is still fresh. Without a structured closeout step, those observations are easy to lose or keep as private notes instead of improving the shared repository.

`spec-kit-retrospect` provides `/speckit.retrospect.run`, a read-only-first workflow that reports findings, assigns dispositions, and waits for approval before writing files, creating issues, or preparing PR work.

## How It Works

The extension provides a single command:

```text
/speckit.retrospect.run [optional focus area]
```

The command:

1. Resolves whether the session is inside a spec-kit feature or an ad-hoc branch.
2. Reviews the current conversation and relevant repo context.
3. Groups findings into instructions/configuration gaps, documentation gaps, architectural friction, and mistakes/corrections.
4. Assigns each finding to `fix-now`, `open-pr`, `github-issue`, or `local-only`.
5. Saves the report only after approval.
6. Executes only the approved disposition buckets.

## Safety Model

The command is read-only until the user approves saving the report or acting on disposition buckets. It must not silently edit files, commit, push, open PRs, or create GitHub issues.

Ask First topics from `AGENTS.md`, including database migrations, GraphQL schema changes, new dependencies, CI/CD workflow changes, authentication, and authorization, are never assigned to `fix-now`. Generated files are never edited.

## Installation

```bash
specify extension add /path/to/spec-kit-retrospect --dev
```

## Usage

```text
/speckit.retrospect.run
/speckit.retrospect.run focus on GraphQL propagation friction
```

## Report Location

When run inside a spec-kit feature, the report is saved to:

```text
specs/<current-feature>/retrospective.md
```

For ad-hoc sessions, the report is saved to:

```text
.claude/retrospectives/YYYYMMDD-HHMMSS-<short-branch-or-session-slug>.md
```

If a report already exists at the target path, use a numeric suffix rather than overwriting it.

## Project Structure

```text
extension.yml             # Extension metadata and command registration
commands/
  retrospect.md           # Command definition for the retrospective workflow
```

## License

[MIT](LICENSE)
