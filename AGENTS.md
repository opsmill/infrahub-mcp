# Infrahub MCP Server

Connects AI assistants to Infrahub over the open MCP standard, so agents can read and (optionally) change infrastructure state through a consistent, audited, human-approved interface.

## Tech Stack

- **Runtime:** Python 3.13, FastMCP, Infrahub SDK, Pydantic 2, Starlette
- **Testing:** pytest, pytest-asyncio
- **Linting:** ruff, mypy, pylint, yamllint
- **Docs:** Docusaurus (`.mdx` in `docs/docs/`), rumdl for markdown linting
- **Package Manager:** uv

## File Structure

- `src/infrahub_mcp/` — Library source code
  - `tools/` — MCP tool implementations (gql, nodes, schema, session, write)
  - `resources/` — MCP resources (branches, schema)
  - `prompts/` — MCP prompt templates
  - `middleware.py` — Full middleware stack (logging, caching, auth, rate limiting, audit)
  - `server.py` — FastMCP server construction and ASGI app
  - `config.py` — `ServerConfig` via pydantic-settings
  - `auth.py` — OIDC provider factory and identity helpers
- `tests/` — Test suite
- `docs/` — User-facing documentation (Docusaurus)
- `dev/` — Internal developer documentation — see [dev/README.md](dev/README.md)
- `.agents/` — AI agent commands and skills
- `.specify/` — Speckit scaffolding (templates, workflows, extensions)

## Commands

```bash
uv sync                          # Install dependencies

uv run pytest                    # Run full test suite

uv run invoke format             # Auto-format with ruff and apply lint autofixes
uv run invoke lint               # All linters (yaml -s, ruff check + format-check, mypy, ty, pylint, rumdl, vale)
uv run invoke validate           # docker-compose env vars + server.json env vars + CAPABILITIES.md freshness
uv run invoke ci                 # Full CI mirror: lint + validate + docs build + pytest. Run before pushing.
uv run invoke ci --no-docs       # Same, minus the docs website build (prints a skipped-gate banner)
uv run invoke lint-ruff          # Ruff only (mirrors CI: check + format --check --diff)
uv run invoke lint-pylint        # Pylint only
uv run invoke lint-mypy          # MyPy type checking only (src/infrahub_mcp)
uv run invoke lint-ty            # ty type checking only (whole tree, mirrors CI)
uv run invoke lint-yaml          # Yamllint strict (-s, mirrors CI)
uv run invoke lint-markdown      # rumdl on docs/ (mirrors CI's markdown-lint job)
uv run invoke lint-vale          # Vale documentation style (fails if the vale binary is absent)

uv run rumdl check docs/docs/    # Check markdown linting (CI scope is the wider docs/)
uv run rumdl fmt docs/docs/      # Auto-fix markdown formatting
uv run invoke docs               # Build the docs website (mirrors CI; needs docs/node_modules)
cd docs && pnpm install --frozen-lockfile   # Install docs deps once, as CI does
brew install vale                # Vale binary (one-time, required for invoke lint-vale and invoke ci)

uv run pre-commit run            # Ruff + rumdl on staged files, Mypy on src/
uv run pre-commit install        # Optional: run those same hooks on every commit
```

`ruff`, `mypy`, and `ty` are authoritative for Python syntax, style, and type issues. Do not eyeball Python errors — run `uv run invoke format ci` and rely on the output.

The `invoke ci` task mirrors every gate a pull request runs: the lint jobs (ruff, ty, yamllint, rumdl, Vale), the `validate-*` jobs, the docs website build, and the unit tests from `.github/workflows/ci.yml`, plus the `validate-capabilities` job from `.github/workflows/ci-mcp-discovery.yml` — a separate workflow that fires on any change under `src/infrahub_mcp/**`. It runs them unconditionally, whereas CI path-gates most jobs off `files-changed` — so `invoke ci` is stricter than CI, never looser. Two things break that symmetry: `--no-docs` drops the docs build (the run then prints a skipped-gate banner and no longer predicts CI), and CI lints the PR merged with its base while `invoke ci` only sees the working tree. A clean `invoke ci` otherwise predicts CI pass; if CI flags something it missed, treat that gap as a bug in `tasks.py` and patch the task.

## MCP Objects

Changes to MCP functionality typically span all three object types:

- **Tools** (`src/infrahub_mcp/tools/`) — write tools MUST be tagged `"write"`
- **Resources** (`src/infrahub_mcp/resources/`)
- **Prompts** (`src/infrahub_mcp/prompts/`)

## Middleware

The stack is composed once at startup via `configure_middleware()` in `middleware.py`. Keep all middleware classes there; do not scatter them. Wire activation through `ServerConfig` flags. The 17-layer ordering (outermost → innermost) and rationale live in [dev/knowledge/architecture.md](dev/knowledge/architecture.md) and [dev/adr/0002-middleware-stack-ordering.md](dev/adr/0002-middleware-stack-ordering.md).

## Coding Standards

- **Python:** [dev/guidelines/python.md](dev/guidelines/python.md)
- **Architecture:** [dev/knowledge/architecture.md](dev/knowledge/architecture.md)
- **Constitution:** [dev/constitution.md](dev/constitution.md)

## Boundaries

### Always Do

- Run `uv run invoke format ci` before pushing — applies autofixes, then runs the full CI mirror (lint, markdown, docs style, repo-state validation, docs website build, tests)
- When adding a new `ServerConfig` field, land it in every location on the [config-field checklist](dev/guidelines/feature-completion.md#new-serverconfig-field) — that list is authoritative, and it marks which entries CI actually enforces (`server.json` and `docker-compose.yml`) versus which are convention only
- After implementing a feature scaffolded under `specs/`, follow the [spec lifecycle](dev/guidelines/feature-completion.md#spec-lifecycle) — extract durable decisions into `dev/adr/`, archive the spec under `specs/archive/`
- Use Infrahub SDK for all Infrahub operations (never raw HTTP)
- Tag write tools with `"write"`
- Validate configuration at startup via `ServerConfig`
- Use `ContextVar` for per-request state (never global mutable state)

### Ask First

- Adding new dependencies
- Changing authentication behavior
- Modifying the middleware stack order
- Schema or API contract changes

### Never Do

- Hardcode secrets or credentials
- Force push to `stable`
- Bypass the SDK for Infrahub API calls
- Add `Any` to public interfaces without justification

## Navigation

Internal developer docs are indexed in [dev/README.md](dev/README.md): architecture in [dev/knowledge/](dev/knowledge/), how-to guides in [dev/guides/](dev/guides/), coding rules in [dev/guidelines/](dev/guidelines/), decisions in [dev/adr/](dev/adr/), project rules in [dev/constitution.md](dev/constitution.md), and agent commands in [.agents/commands/](.agents/commands/).

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
<!-- SPECKIT END -->
