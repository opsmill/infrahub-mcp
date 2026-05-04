# Developer Documentation

Internal documentation for infrahub-mcp contributors. For user-facing docs, see `/docs/`.

## Quick Navigation

| I want to...                     | Go to              |
|----------------------------------|---------------------|
| Understand the architecture      | `knowledge/`        |
| Follow coding standards          | `guidelines/`       |
| Learn why we made a decision     | `adr/`              |
| Read the project constitution    | `constitution.md`   |
| Use agent commands               | `../.agents/commands/` |

## Directory Guide

- **constitution.md**: Project principles, quality gates, governance. The authoritative reference.
- **adr/**: Architecture Decision Records. Why we chose what we chose.
- **guidelines/**: Prescriptive rules. How code should be written.
- **knowledge/**: Descriptive reference. How the system works.

Agent commands live at the repository root under `.agents/commands/`:

- [create-issue](../.agents/commands/create-issue.md) - Transform ideas into well-structured GitHub issues
- [pr](../.agents/commands/pr.md) - Full PR workflow: commit, analyze, document, create, monitor CI
- [rebase](../.agents/commands/rebase.md) - Safe rebase onto stable with conflict resolution
- [speckit.extract](../.agents/commands/speckit.extract.md) - Extract ADRs/knowledge/guidelines from completed specs

## Document Lifecycle

```text
idea → ADR or spec → knowledge/ or guidelines/
```

Mark deprecated docs clearly. Don't delete — update with pointers to replacements.

## Current Guidelines

- [Python](guidelines/python.md) - Python coding standards, FastMCP patterns, testing conventions
- [Feature completion](guidelines/feature-completion.md) - Post-implementation checklist: env-var registration, spec→ADR→archive lifecycle, pre-push CI mirror

## Current Knowledge

- [Architecture](knowledge/architecture.md) - MCP server architecture: middleware, tools, resources, auth

## Current ADRs

- [0001](adr/0001-context-nuggets-pattern.md) - Context Nuggets Pattern for Repository Organization
- [0002](adr/0002-middleware-stack-ordering.md) - Middleware Stack Ordering (17-layer, composed at startup)
- [0003](adr/0003-dual-layer-authentication.md) - Dual-Layer Authentication (ASGI + MCP middleware)
- [0004](adr/0004-tag-based-read-only-mode.md) - Tag-Based Read-Only Mode with Defense-in-Depth
- [0005](adr/0005-lazy-session-branch-creation.md) - Lazy Session Branch Creation with Collision Retry
- [0006](adr/0006-config-validation-at-boundary.md) - Configuration Validation at Boundary, Not Model
- [0007](adr/0007-hash-validated-schema-cache.md) - Hash-Validated Schema Cache for Passthrough Auth Modes
