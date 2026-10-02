# spec-kit-auto

A [spec-kit](https://github.com/github/spec-kit) extension that runs the full speckit workflow end-to-end in a single hands-off invocation — specify, plan, tasks, implement, review, extract — making all decisions autonomously.

## What Problem Does This Solve?

The standard speckit workflow is a sequence of agent commands that each pause for user review. That's the right default for high-stakes work, but it's overkill when you want to throw a feature description at the agent and walk away. `spec-kit-auto` runs the whole pipeline back-to-back, committing after each phase, so you can come back to a finished feature instead of babysitting the loop.

## How It Works

The extension provides a single command, `/speckit.auto.run`, which orchestrates the full speckit pipeline:

1. **Specify** — `/speckit.specify` with the user's feature description
2. **Plan** — `/speckit.plan`
3. **Tasks** — `/speckit.tasks`
4. **Implement** — `/speckit.implement`
5. **Review** — `/speckit.review` (high-severity findings are fixed inline)
6. **Extract** — `/speckit.extract.run` to harvest ADRs, knowledge, and guidelines

After each phase, the agent invokes `/speckit.checkpoint.commit` to commit the artifacts produced. Clarifications and design decisions are made autonomously — the workflow does not pause for user input between phases.

## Quick Start

### Prerequisites

- [spec-kit](https://github.com/github/spec-kit) >= 0.1.0
- The following speckit commands available in your environment:
  - `speckit.specify`, `speckit.plan`, `speckit.tasks`, `speckit.implement`
  - `speckit.review` (from the `review` extension)
  - `speckit.extract.run` (from the `extract` extension)
  - `speckit.checkpoint.commit` (from the `checkpoint` extension)

### Installation

```bash
specify extension add /path/to/spec-kit-auto --dev
```

## Usage

```
/speckit.auto.run <feature description>
```

The agent will run all six phases in order, committing after each one, and report a summary when finished:

- Feature name and spec directory
- Number of tasks completed
- Any review findings that were fixed
- Any notable decisions made autonomously

## When to Use This

Reach for `/speckit.auto.run` when the feature is well-scoped enough that you trust the agent to make reasonable judgment calls without you in the loop. For high-stakes or ambiguous work, prefer running the phases individually so you can review between steps.

## Project Structure

```
extension.yml          # Extension metadata and command registration
commands/
  run.md               # Command definition for the full pipeline
```

## License

[MIT](LICENSE)
