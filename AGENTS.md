# LLM Context Guide for Infrahub MCP Server

Infrahub MCP Server connects your AI assistants to Infrahub using the open MCP standard—so agents can read and (optionally) change your infra state through a consistent, audited, human-approved interface.

## Agent Operating Principles

1. **Plan → Ask → Act → Verify → Record**
   Plan briefly, ask for missing context, act via the narrowest tool, verify the result, and leave a succinct record (commit/PR/comment).

2. **Default to read-only.**
   Switch to write/apply only with explicit instruction **and** human approval.

3. **Be specific and reversible.**
   Prefer minimal, scoped changes that are easy to roll back. Avoid broad or implicit mutations.

4. **Match existing patterns.**
   New code and behavior should look like it’s always been here.

5. **Idempotency & safety.**
   Favor idempotent operations; use dry-runs where available; never print or guess secrets.

## Required Development Workflow

**CRITICAL**: Always run these commands in sequence before committing:

```bash
uv sync                    # Install dependencies
uv run pre-commit run      # Ruff + Mypy
uv run pytest              # Run full test suite
```

**All three must pass** — enforced by CI. Alternatives (granular tasks):

```bash
uv run invoke lint              # Run all linters (yaml, ruff, pylint, mypy)
uv run invoke lint-ruff         # Run ruff linter only
uv run invoke lint-pylint       # Run pylint only
uv run invoke lint-mypy         # Run mypy type checking only
uv run invoke lint-yaml         # Run yamllint only
uv run invoke format            # Auto-format code with ruff
```

**Policy:** Tests must pass and lint/typing must be clean before committing.

## Repository Structure

```bash
infrahub-mcp/
├── docs/                       # Documentation (UPDATE FOR CHANGES)
├── src/infrahub_mcp            # Library source code (Python ≥ 3.13)
|   ├── prompts/                # Prompt templates
|   ├── resources/              # Resources, templates
|   └── tools/                  # Tool implementations
└── tests/                      # Python/integration tests
```

## Core MCP Objects

When modifying MCP functionality, changes typically need to be applied across all object types:

- **Tools** (`src/infrahub_mcp/tools/`)
- **Resources** (`src/infrahub_mcp/resources/`)
- **Prompts** (`src/infrahub_mcp/prompts/`)

## Code Standards (single source of truth)

### Python

- **Python ≥ 3.13** with **full type annotations** for all new/changed code.
- **MyPy clean** — `uv run pre-commit run mypy`
- **Ruff clean** — `uv run pre-commit run ruff`
- Prefer clear, maintainable code over cleverness.
- Public functions/classes **must** have docstrings (consistent style).
- Raise **specific exceptions**; avoid bare `except:`.
- For MCP result objects in tests, use `# type: ignore[attr-defined]` instead of brittle type assertions.

### Testing

- Every test is atomic, self-contained, and targets **one** behavior.
- Use **parametrization** for variants; avoid loops in tests.
- Imports at file top; no dynamic imports inside tests.
- **ALWAYS** run `uv run pytest` after significant changes.
- Each feature requires corresponding tests (happy path + key edge cases).

## Documentation

- **docs/**: Update for any user-facing changes
- **Docstrings**: Required for new functions/classes

### Documentation Guidelines

- All documentation files are in `docs/docs/` and use `.mdx` format
- **ALWAYS run markdownlint before committing documentation changes**: `markdownlint docs/docs/**/*.mdx`
- Use `markdownlint --fix docs/docs/**/*.mdx` to automatically fix formatting issues
- Follow the project's `.markdownlint.yaml` configuration
- Test documentation builds with `cd docs && npm run build` before submitting
- Documentation follows the Diataxis framework (Getting Started, Features, Guides, Reference)

### Documentation Build

```bash
uv run invoke docs              # Build documentation website (requires npm)
```

## Development Rules

### Git & CI

- Pre-commit hooks are required (run automatically on commits).
- Don’t amend commits to fix pre-commit failures; make a follow-up commit.
- Apply PR labels: **bugs / breaking / enhancements / features**.
- Improvements = **enhancements** unless explicitly a **feature**.
- **NEVER** force-push on collaborative repos.
- **ALWAYS** run pre-commit before PRs.

### Commit Messages & Agent Attribution

- **Agents MUST identify themselves** (e.g., `🤖 Generated with Claude Code`) in commits/PRs.
- Keep messages brief — headline of **what** changed. (How/why goes in the PR body.)
- Always read issue comments for context; maintainers are authoritative.

### PR Messages — Required Structure

- 1–2 concise paragraphs: **problem/tension** + **solution** (PRs are documentation).
- A focused **code example** showing the key capability.
- **Avoid:** bullet dumps, exhaustive change lists, verbose closes/fixes, marketing language.
- **Do:** explain why the change matters; show before/after when helpful.
- Minor fixes: keep the body extremely short.
- No separate “test plan” sections or testing summaries.

## Review Process (for humans and agents)

- **Read the full context** (related files, tests, docs).
- **Check against established patterns**; keep consistency.
- **Verify functionality claims** by tracing the code and, if possible, running a focused check.
- **Consider edge cases** (timeouts, empty inputs, network/permission errors).

### Avoid in Reviews

- Generic feedback without specifics
- Unlikely hypotheticals
- Bikeshedding style when functionality is correct
- Requests without suggested solutions
- Summarizing what’s already in the PR

### Tone

- Acknowledge good decisions (“This API design is clean”).
- Be direct and respectful.
- Explain impact (“This will confuse users because …”).
- Remember: someone else maintains this code forever.

### Decision Framework (before approve)

1. Does this PR achieve its stated purpose?
2. Is that purpose aligned with where the codebase should go?
3. Would I be comfortable maintaining this code?
4. Do I actually understand what it does (not just claims)?
5. Does this change introduce technical debt?

If something needs work, help it get there with **specific, actionable** feedback. If it solves the wrong problem, say so clearly.

### Review Comment Examples

- ❌ “Add more tests”
  ✅ “The `handle_timeout` method needs tests for the edge case where `timeout=0`.”
- ❌ “This API is confusing”
  ✅ “The parameter name `data` is ambiguous—consider `message_content` to match the MCP specification.”
- ❌ “This could be better”
  ✅ “Works, but creates a circular dependency. Consider moving the validation to `utils/validators.py`.”

### Review Checklist

Before approving, verify:

- [ ] All required workflow steps completed (uv sync, pre-commit, pytest)
- [ ] Changes align with repository patterns and conventions
- [ ] API changes are documented and backwards-compatible where possible
- [ ] Error handling follows project patterns (specific exception types)
- [ ] Tests cover new functionality and edge cases

## Operational & Safety Guidelines for Agents

- **Human approval required** before any write/apply operation. Present a clear plan and a diff.
- Prefer **dry runs** and attach their output to the PR where available.
- **Least privilege**: call the most specific tool with the smallest scope.
- **Idempotency & retries**: safe to re-run; add backoff on transient failures.
- **Observability**: include request IDs and context in logs; never log secrets.
- **Concurrency**: avoid stepping on active branches/migrations; coordinate via PRs.

> If unsure, **stop and ask** with a concrete question.

## Security & Secrets

- Configure credentials via **environment variables**; never hardcode.
- Never print tokens, keys, or sensitive paths in logs, exceptions, or PRs.
- Redact sensitive values in examples and tests.

## Platform-Specific Instructions

- **[CLAUDE.md](CLAUDE.md)** - For Claude/Anthropic tools
- **[.github/copilot-instructions.md](.github/copilot-instructions.md)** - For GitHub Copilot
- **[GEMINI.md](GEMINI.md)** - For Google Gemini tools
- **[GPT.md](GPT.md)** - For OpenAI/ChatGPT tools
- **[.cursor/rules/dev-standard.mdc](.cursor/rules/dev-standard.mdc)** - For Cursor editor
