# 1. Context Nuggets Pattern for Repository Organization

**Status:** Accepted
**Date:** 2026-04-21
**Author:** @bkohler

## Context

The infrahub-mcp repository needs structured documentation for both
human and AI contributors. The initial approach — a single `AGENTS.md`
file containing all coding standards, architecture knowledge, and
operational guidelines — does not scale well:

- AI agents load the entire file into context even when only a subset
  is relevant, wasting tokens and diluting attention.
- Contributors must scroll through unrelated sections to find what
  they need.
- There is no clear place for architectural decisions, coding
  guidelines, or system knowledge to live independently.

The parent project (Infrahub) successfully adopted the "Context
Nuggets" pattern (see Infrahub ADR-0001), organizing developer
documentation into small, focused files (200-400 lines) with clear
ownership and purpose.

## Decision

Adopt the Context Nuggets pattern for Infrahub MCP, adapted for a
focused Python project rather than a monorepo.

### Core Structure

- **`dev/`**: Centralizes internal developer documentation organized
  by purpose:
  - `constitution.md` — project principles and governance
  - `adr/` — Architecture Decision Records
  - `guidelines/` — prescriptive rules (how to write code)
  - `knowledge/` — descriptive reference (how the system works)

- **`.agents/`**: AI agent commands and skills at the repository root:
  - `commands/` — reusable agent commands
  - `skills/` — domain-specific skill guides

- **Tool compatibility via symlinks:**
  - `.claude/commands` → `../.agents/commands`
  - `.claude/skills` → `../.agents/skills`
  - `.specify/memory/constitution.md` → `../../dev/constitution.md`

- **`AGENTS.md`** becomes a lightweight map (~100 lines) with pointers
  to detailed docs, not a knowledge dump.

### Key Principles

- Small, focused files over monolithic documents.
- Symlink to maintain a single source of truth across tools.
- Directories created on demand — no empty placeholders.
- `dev/README.md` serves as the navigation index.

## Consequences

### Positive

- AI agents can load only the relevant context nugget, saving tokens.
- Claude Code slash commands work via the `.claude/commands` symlink.
- Speckit reads the constitution via the `.specify/memory` symlink.
- Clear separation: guidelines (how) vs. knowledge (what) vs. ADRs (why).
- Pattern consistency across Opsmill repositories.

### Negative

- Initial setup overhead (directories, symlinks, content migration).
- Contributors must learn the directory convention.

### Neutral

- The `.specify/` directory continues to hold Speckit scaffolding
  (templates, workflows, extensions) — it is not replaced by `dev/`.

## Alternatives Considered

### Keep everything in AGENTS.md

Simpler but does not scale. AI agents pay the full token cost on every
interaction, and there is no place for ADRs or structured knowledge.

### Use `.specify/` for everything

Speckit's `.specify/` directory is purpose-built for the specification
workflow (specs, plans, tasks). Developer documentation (guidelines,
knowledge, ADRs) has a different lifecycle and audience.
