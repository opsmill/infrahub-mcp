---
description: Transform feature descriptions, bug reports, or improvement ideas into well-structured GitHub issues.
---

# Create GitHub Issue

## Introduction

Transform feature descriptions, bug reports, or improvement ideas into well-structured GitHub issues that follow project conventions and best practices. This command provides flexible detail levels to match your needs.

## Prerequisites

- GitHub CLI (`gh`) installed and authenticated
- Current directory is within the infrahub-mcp repository

## Feature Description

<arguments> #$ARGUMENTS </arguments>

## Main Tasks

### 1. Repository Research & Context Gathering

<thinking>
Before writing anything, understand the landscape — what exists, what's related, and what the conventions are.
</thinking>

- [ ] Identify the repository and confirm access:
  ```bash
  gh repo view --json nameWithOwner -q '.nameWithOwner'
  ```
- [ ] Check for related existing issues:
  ```bash
  gh issue list --state open --limit 20
  gh issue search "<keywords>" --limit 10
  ```
- [ ] Review project structure for relevant context:
  - `dev/constitution.md` — project principles
  - `dev/knowledge/architecture.md` — architecture overview
  - `src/infrahub_mcp/` — source code layout
- [ ] Identify relevant labels:
  ```bash
  gh label list
  ```
- [ ] Check recent PRs for similar patterns:
  ```bash
  gh pr list --state merged --limit 10
  ```

### 2. Issue Planning & Structure

<thinking>
Think like a product manager — what would make this issue clear and actionable? Consider multiple perspectives.
</thinking>

**Title & Categorization:**

- [ ] Draft clear, searchable issue title using conventional format (e.g., `feat:`, `fix:`, `docs:`)
- [ ] Identify appropriate labels from repository's label set
- [ ] Determine issue type: enhancement, bug, documentation, refactor
- [ ] Consider adding priority labels if available

**Stakeholder Analysis:**

- [ ] Identify who will be affected by this issue (MCP users, developers, operators)
- [ ] Note any cross-project dependencies (infrahub-sdk, FastMCP)

**Content Planning:**

- [ ] Choose appropriate detail level based on issue complexity and audience
- [ ] List all necessary sections for the chosen template
- [ ] Gather supporting materials (error logs, configuration examples)

### 3. Choose Implementation Detail Level

Based on the complexity and scope, choose ONE of these templates:

#### MINIMAL (Quick Issue)

For simple bugs, typos, or straightforward improvements:

```markdown
## Description
[2-3 sentences explaining what and why]

## Expected Behavior
[What should happen]

## Acceptance Criteria
- [ ] [Single clear criterion]
```

#### STANDARD (Standard Issue)

For features, enhancements, and non-trivial bugs:

```markdown
## Description
[Problem statement and proposed solution]

## Context
[Why this matters — user impact, technical motivation]

## Requirements
- [ ] [Requirement 1]
- [ ] [Requirement 2]

## Acceptance Criteria
- [ ] [Criterion 1]
- [ ] [Criterion 2]

## Technical Notes
[Implementation hints, relevant files, dependencies]
```

#### COMPREHENSIVE (Comprehensive Issue)

For significant features or architectural changes:

```markdown
## Description
[Problem statement, proposed solution, and scope]

## Context & Motivation
[Business/technical motivation, user stories or scenarios]

## Requirements

### Functional
- [ ] [Requirement 1]
- [ ] [Requirement 2]

### Non-Functional
- [ ] [Performance, security, or compatibility requirements]

## Technical Design
[Architecture notes, affected components, API changes]

### Affected Areas
- [ ] Tools (`src/infrahub_mcp/tools/`)
- [ ] Resources (`src/infrahub_mcp/resources/`)
- [ ] Middleware (`src/infrahub_mcp/middleware.py`)
- [ ] Configuration (`src/infrahub_mcp/config.py`)

## Acceptance Criteria
- [ ] [Criterion 1]
- [ ] [Criterion 2]

## Testing Strategy
[What needs testing — unit, integration, manual verification]

## Documentation
[What docs need updating — `docs/docs/`, `dev/knowledge/`, `dev/guidelines/`]
```

### 4. Issue Creation & Formatting

- [ ] Write the issue content following the chosen template
- [ ] Ensure all code blocks use appropriate language identifiers
- [ ] Verify all links and references are valid
- [ ] Cross-reference related issues where applicable
- [ ] Add relevant constitution principles if the issue touches core patterns (e.g., "Aligns with Principle I: MCP Protocol Compliance")

### 5. User Validation & Submission

1. Present the complete draft issue content to the user for review
2. Wait for the user's explicit approval or requested changes
3. Only after approval, create the issue:

```bash
gh issue create --title "[TITLE]" --body "[CONTENT]" --label "[LABELS]"
```

4. Report the created issue URL to the user

## Output Format

1. Present the complete draft issue content to the user for review
2. Wait for the user's explicit approval or requested changes
3. Only after approval, create the issue using GitHub CLI

## Notes

- **Never create issues without user approval** — always present the draft first
- **Search before creating** — duplicate issues waste everyone's time
- **Labels matter** — they drive project boards and triage workflows
- **Link related issues** — use `Related to #NNN` or `Depends on #NNN`
- **Be specific** — "it doesn't work" is not an issue description

## Expected Outcome

A well-structured GitHub issue that:

- Has a clear, searchable title with conventional prefix
- Uses the appropriate detail level for its complexity
- Includes all relevant context and acceptance criteria
- Is properly labeled and cross-referenced
- Has been reviewed and approved by the user before creation
