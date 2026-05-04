---
description: Extract ADRs, knowledge, and guidelines from completed specifications into dev/ documentation.
handoffs:
  - label: Build Specification
    agent: speckit.specify
    prompt: Implement the feature specification. I want to build...
---

## User Input

```text
$ARGUMENTS
```

You **MUST** consider the user input before proceeding (if not empty).

## Outline

1. Phase 0: Setup & Validation
2. Phase 1: Analysis & Classification
3. Phase 2: Interactive Review
4. Phase 3: Write Extractions
5. Phase 4: Cleanup & Report

## Phase 0: Setup & Validation

1. Determine target spec(s):
   - If user provided a spec name: locate it in `.specify/` or `specs/`
   - If no argument: scan for specs with status `implemented` or `completed`
   - If no completed specs found: report and exit

2. For each target spec, read:
   - `spec.md` (the specification)
   - `research.md` (if exists — research notes from implementation)
   - `plan.md` (if exists — implementation plan)
   - `tasks.md` (if exists — task breakdown)

3. Read existing documentation to avoid duplicates:
   - `dev/adr/` — existing ADR files
   - `dev/knowledge/` — existing knowledge docs
   - `dev/guidelines/` — existing guideline docs

4. Determine next ADR number from existing files in `dev/adr/`.

## Phase 1: Analysis & Classification

### Step 1: Extract ADR candidates

Parse the spec and research files. For each significant decision:

1. Extract: Decision, Rationale, Alternatives considered, Implementation pattern
2. Determine if ADR-worthy:
   - **ADR-worthy**: Affects system structure, API contracts, middleware composition, MCP protocol behavior, authentication patterns, or establishes a pattern used across multiple components
   - **Not ADR-worthy**: One-off implementation detail with no broader implications
3. Draft an ADR title (concise, decision-focused)

### Step 2: Extract knowledge candidates

Identify content that documents how the system works:

- New architectural patterns or components
- Request/response flows
- Integration points with Infrahub SDK
- Middleware behavior changes

Determine target file: new doc in `dev/knowledge/` or update to existing `dev/knowledge/architecture.md`.

### Step 3: Extract guideline candidates

Identify content that prescribes how code should be written:

- New coding patterns established during implementation
- FastMCP usage patterns discovered
- Testing patterns for new component types

Determine target: new doc in `dev/guidelines/` or update to existing `dev/guidelines/python.md`.

### Step 4: Identify skipped content

Note content intentionally skipped (execution artifacts, temporary state, plan details) with reasons.

## Phase 2: Interactive Review

Present findings in a structured extraction plan:

```markdown
## Extraction Plan

#### ADRs to Create (<count>)

| # | Source | Title | Target File |
|---|--------|-------|-------------|
| 1 | spec.md | <title> | dev/adr/adr-NNN-<slug>.md |

#### Knowledge Updates (<count>)

| # | Target File | Section | Change | Summary |
|---|-------------|---------|--------|---------|
| 2 | dev/knowledge/architecture.md | Middleware | UPDATE | <what changes> |

#### Guidelines Updates (<count>)

| # | Target File | Section | Change | Summary |
|---|-------------|---------|--------|---------|
| 3 | dev/guidelines/python.md | FastMCP Patterns | UPDATE | <what changes> |

#### Skipped (with reasons)

| Source | Reason |
|--------|--------|
| plan.md | Execution artifact — no durable knowledge |
```

After presenting, tell the user:

> **Actions:**
> - `approve all` — proceed with all extractions
> - `approve adrs` / `approve knowledge` / `approve guidelines` — approve by category
> - `skip N` — skip a specific numbered item
> - `edit N` — modify a specific item before writing
> - `group N,M` — merge multiple ADR items into a single ADR

Wait for user response before proceeding. Do NOT write any files until the user approves.

## Phase 3: Write Extractions

### ADRs

For each approved ADR, use the template at `.specify/templates/adr-template.md`:

1. Copy template to `dev/adr/NNNN-<slug>.md`
2. Fill in all sections from the extracted content
3. Set Status to `Accepted` and Date to today

### Knowledge updates

For each approved knowledge update:

1. If new file: create in `dev/knowledge/` with clear heading structure
2. If update: read existing file, add/modify the relevant section
3. Keep files under 400 lines — split if necessary

### Guidelines updates

For each approved guideline update:

1. If new file: create in `dev/guidelines/` with clear heading structure
2. If update: read existing file, add/modify the relevant section

## Phase 4: Cleanup & Report

### 1. Create extraction record

Write `EXTRACTED.md` in the spec directory:

```markdown
# Extraction Record

**Extracted on**: <YYYY-MM-DD>
**Extracted by**: speckit.extract

## ADRs Created

- <path to ADR file> (from <source>)

## Knowledge Updated

- <path to knowledge file> (<section name>)

## Guidelines Updated

- <path to guidelines file> (<section name>)

## Archive

Spec directory moved to `specs/archive/<spec-name>/` as a historical record.
```

### 2. Update dev/README.md

Add entries to the appropriate index sections (Current ADRs, Current Knowledge, Current Guidelines).

### 3. Report

Output a summary:

```
## Extraction Complete

- **ADRs created**: N
- **Knowledge docs updated**: N
- **Guidelines updated**: N
- **Spec archived**: yes/no

Files modified:
- <list of all created/modified files>
```

## Behavior Rules

- Never write files without user approval from Phase 2.
- Always use the ADR template from `.specify/templates/adr-template.md`.
- Preserve existing content when updating files — append or modify sections, don't overwrite.
- Keep all documentation files under 400 lines.
- Use relative paths in all cross-references.
