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

uv run invoke format             # Auto-format with ruff
uv run invoke lint               # All linters (yaml, ruff, pylint, mypy)
uv run invoke lint-ruff          # Ruff only
uv run invoke lint-pylint        # Pylint only
uv run invoke lint-mypy          # MyPy type checking only
uv run invoke lint-yaml          # Yamllint only

uv run rumdl check docs/docs/    # Check markdown linting
uv run rumdl fmt docs/docs/      # Auto-fix markdown formatting
cd docs && npm run build         # Test documentation build

uv run pre-commit run            # Ruff + Mypy (runs automatically on commits)
```

`ruff` and `mypy` are authoritative for Python syntax, style, and type issues. Do not eyeball Python errors — run `uv run invoke format lint` and rely on the output.

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

- Run `uv sync && uv run pre-commit run && uv run pytest` before committing
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

Internal developer docs are indexed in [dev/README.md](dev/README.md): architecture in [dev/knowledge/](dev/knowledge/), coding rules in [dev/guidelines/](dev/guidelines/), decisions in [dev/adr/](dev/adr/), project rules in [dev/constitution.md](dev/constitution.md), and agent commands in [.agents/commands/](.agents/commands/).

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
<!-- SPECKIT END -->
