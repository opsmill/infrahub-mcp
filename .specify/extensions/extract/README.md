# spec-kit-extract

A [spec-kit](https://github.com/github/spec-kit) extension that distills durable knowledge out of completed feature specifications. Given one or more spec directories, the agent classifies their content into ADRs, knowledge documents, and guidelines, walks the user through an approval gate, then writes the extractions into the project's documentation tree and archives the source spec.

## What Problem Does This Solve?

Feature specs accumulate valuable context — architectural decisions, system behavior, prescriptive patterns — that gets lost once the work merges. Without an extraction step, every new contributor has to re-read old `specs/###-*` directories to recover institutional knowledge. `spec-kit-extract` operationalizes the documentation lifecycle (`specs/ → dev/knowledge/`, `dev/guidelines/`, or `dev/adr/`) so each finished feature leaves the project's docs better than it found them.

## How It Works

The extension provides a single command, `/speckit.extract`, that processes one or more completed spec directories in four phases:

1. **Setup & Validation** — resolve spec identifiers, validate required artifacts, load the existing documentation index.
2. **Analysis & Classification** — parse `research.md`, `spec.md`, `data-model.md`, and `contracts/`, then classify findings as ADR-worthy, knowledge, guideline, or skip.
3. **Interactive Review** — present a numbered extraction plan and wait for the user to approve, skip, edit, or group items. No files are written before approval.
4. **Write & Archive** — create ADRs in `dev/adr/`, append knowledge and guideline updates with traceability markers, write an `EXTRACTED.md` record, update `dev/README.md`, and move the spec into `specs/archive/<spec-name>/`.

ADR numbering is sequential across the entire batch, so multiple specs can be extracted in a single invocation without collisions.

## Quick Start

### Prerequisites

- [spec-kit](https://github.com/github/spec-kit) >= 0.1.0
- A project layout with `specs/` for feature directories and `dev/knowledge/`, `dev/guidelines/`, `dev/adr/` for documentation outputs

### Installation

```bash
specify extension add /path/to/spec-kit-extract --dev
```

## Usage

```
/speckit.extract specs/007-feature-one specs/012-feature-two
```

Or by bare slug:

```
/speckit.extract graphql-name-lookup
```

If no arguments are passed, the agent lists available spec directories and asks which to process. The interactive review supports `approve all`, `approve spec <name>`, `approve adrs|knowledge|guidelines`, `skip N`, `edit N`, and `group N,M` actions.

## When to Use This

Run `/speckit.extract` after a feature has merged and you have its `spec.md`, `research.md`, and design artifacts in hand. Extract early enough that the rationale is still fresh, but only once the implementation has stabilized — the goal is to capture decisions that survived contact with reality.

## Project Structure

```
extension.yml          # Extension metadata and command registration
commands/
  extract.md           # Command definition for the extraction workflow
```

## License

[MIT](LICENSE)
