# Infrahub MCP Server

Infrahub MCP Server connects AI assistants to Infrahub using the open MCP standard — so agents can read and (optionally) change infrastructure state through a consistent, audited, human-approved interface.

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

### Setup

```bash
uv sync                    # Install dependencies
```

### Testing

```bash
uv run pytest              # Run full test suite
```

### Linting & Formatting

```bash
uv run invoke format            # Auto-format with ruff
uv run invoke lint              # All linters (yaml, ruff, pylint, mypy)
uv run invoke lint-ruff         # Ruff only
uv run invoke lint-pylint       # Pylint only
uv run invoke lint-mypy         # MyPy type checking only
uv run invoke lint-yaml         # Yamllint only
```

**Important:** `ruff` and `mypy` are the authoritative tools for detecting Python syntax errors, style violations, and type issues. Do not attempt to identify Python errors by reading the code — run `uv run invoke format lint` instead and rely on the tool output.

### Documentation

```bash
uv run rumdl check docs/docs/   # Check markdown linting
uv run rumdl fmt docs/docs/     # Auto-fix markdown formatting
cd docs && npm run build         # Test documentation build
```

### Pre-commit

```bash
uv run pre-commit run            # Ruff + Mypy (runs automatically on commits)
```

## MCP Objects

Changes to MCP functionality typically span all three object types:

- **Tools** (`src/infrahub_mcp/tools/`) — write tools MUST be tagged `"write"`
- **Resources** (`src/infrahub_mcp/resources/`)
- **Prompts** (`src/infrahub_mcp/prompts/`)

## Middleware

The middleware stack is composed once at startup via `configure_middleware()` in `middleware.py`. Do not scatter middleware across modules.

When modifying middleware, you **must**:

1. Understand the 17-layer ordering (outermost → innermost) — see `dev/knowledge/architecture.md`
2. Keep all middleware classes in `middleware.py`
3. Wire activation through `ServerConfig` flags

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

| Question | Location |
|----------|----------|
| How does the system work? | [dev/knowledge/](dev/knowledge/) |
| How should I write code? | [dev/guidelines/](dev/guidelines/) |
| Why was this decided? | [dev/adr/](dev/adr/) |
| What are the project rules? | [dev/constitution.md](dev/constitution.md) |
| What commands are available? | [.agents/commands/](.agents/commands/) |
| Internal docs index | [dev/README.md](dev/README.md) |

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
<!-- SPECKIT END -->
