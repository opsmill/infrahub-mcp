# Infrahub MCP Server

Connects AI assistants to Infrahub over the open MCP standard, so agents can read and (optionally) change infrastructure state through a consistent, audited, human-approved interface.

## Tech Stack

- **Runtime:** Python 3.13, FastMCP, Infrahub SDK, Pydantic 2, Starlette
- **Testing:** pytest, pytest-asyncio
- **Linting:** ruff, ty (CI type checker), mypy (local and pre-commit, `src/` only), pylint, yamllint, Vale (docs prose)
- **Docs:** Docusaurus (`.mdx` in `docs/docs/`, built with pnpm), rumdl for markdown linting
- **Package Manager:** uv

## File Structure

- `src/infrahub_mcp/` — Library source code
  - `tools/` — MCP tool implementations (gql, nodes, schema, session, traversal, write)
  - `resources/` — MCP resources (branches, schema)
  - `prompts/` — MCP prompt templates (the `infrahub_agent` system prompt is in `server.py`)
  - `middleware.py` — Full middleware stack (logging, caching, auth, rate limiting, audit)
  - `server.py` — FastMCP server construction and ASGI app
  - `config.py` — `ServerConfig` via pydantic-settings
  - `auth.py` — OIDC provider factory and identity helpers
  - `schema.py`, `traversal.py` — shared schema-fetching and graph-traversal logic used by the tools and resources
  - `utils.py`, `constants.py` — client and session-branch helpers, shared constants
  - `_cli.py` — `infrahub-mcp` command-line entry point (`--transport`, `--host`, `--port`)
- `tests/` — Test suite: `unit/`, `integration/` (opt-in, uses infrahub-testcontainers), `transport/`
- `development/` — Dockerfile, development docker-compose and Keycloak setup for local OIDC testing
- `docs/` — User-facing documentation (Docusaurus)
- `dev/` — Internal developer documentation — see [dev/README.md](dev/README.md)
- `.agents/` — AI agent commands and skills
- `.specify/` — Speckit scaffolding (templates, workflows, extensions)

## Commands

```bash
uv sync                          # Install dependencies

uv run pytest                    # Run full test suite

uv run invoke format             # Auto-format with ruff
uv run invoke lint               # yamllint, ruff (src/, with --fix), mypy (src/), pylint
uv run invoke lint-ruff          # Ruff on src/ only, applies fixes
uv run invoke lint-pylint        # Pylint only
uv run invoke lint-mypy          # MyPy type checking only
uv run invoke lint-yaml          # Yamllint only

uv run rumdl check docs/docs/    # Check markdown linting
uv run rumdl fmt docs/docs/      # Auto-fix markdown formatting
uv run invoke docs               # Test documentation build (pnpm run build in docs/)

uv run pre-commit run            # Ruff + rumdl on staged files, Mypy on src/
uv run pre-commit install        # Optional: run those same hooks on every commit
```

`ruff` and `ty` are authoritative for Python syntax, style, and type issues: CI runs `uv run ruff check .`, `uv run ruff format --check .` and `uv run ty check .` over the whole repository, while `invoke lint` covers `src/` only. Do not eyeball Python errors — run those commands and rely on the output.

## Changelog

Every pull request that changes behaviour carries a news fragment in `changelog/`. The pull-request check in `.github/workflows/changelog-check.yml` is disabled (its `pull_request` trigger is commented out since 2026-09-16), so no check enforces a fragment per pull request. The **Auto bump version** workflow only refuses to release when `changelog/` holds no fragments at all. `CHANGELOG.md` is assembled from those fragments by towncrier at release time, so entries never collide on a shared file.

- `uv run towncrier create -c "Fixed the thing" 42.fixed.md` — one fragment per change, named `<issue>.<type>.md`. With no issue or PR number, use a descriptive slug prefixed with `+`, e.g. `+schema-cache-ttl.added.md`.
- Types: `security`, `removed`, `deprecated`, `added`, `changed`, `fixed`, `housekeeping`. Internal and tooling work is `housekeeping`.
- `uv run towncrier build --draft --version X.Y.Z` — preview what the release will say.
- Label a PR `ci/skip-changelog` when it genuinely needs no entry (dependency bumps, typo fixes).

Every normal pull request must also carry exactly one release-intent label:
`changes/major`, `changes/minor`, or `changes/patch`. These labels alone
determine the automatic version bump. Generated `chore(release):` pull requests
are exempt because they apply, rather than introduce, that release intent.
Workflows that open any other pull request (`gh pr create`, Dependabot) must
label it `changes/patch`. The gate runs under `pull_request_target` from the base
branch, so it never runs on the pull request that changes it.

Releases are not cut by hand, and merging to `stable` does not prepare one: dispatch the **Auto bump version** workflow from Actions with `stable` selected, which opens a `chore(release): vX.Y.Z` pull request carrying the version bump and the assembled changelog. Merging that pull request tags the release and publishes it with the curated release-notes page, `docs/docs/release-notes/release-X_Y_Z.mdx` (dots in the version become underscores), as the body, falling back to the assembled changelog when that page is missing or fails to render. Never build the changelog or bump versions directly on `stable`.

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

Internal developer docs are indexed in [dev/README.md](dev/README.md): architecture in [dev/knowledge/](dev/knowledge/), how-to guides in [dev/guides/](dev/guides/), coding rules in [dev/guidelines/](dev/guidelines/), decisions in [dev/adr/](dev/adr/), project rules in [dev/constitution.md](dev/constitution.md), and agent commands in [.agents/commands/](.agents/commands/).

<!-- SPECKIT START -->
For additional context about technologies to be used, project structure,
shell commands, and other important information, read the current plan
<!-- SPECKIT END -->
