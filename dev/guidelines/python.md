# Python Coding Standards

Standards for Python code in the infrahub-mcp server. Aligned with
Constitution Principles IV (Type Safety) and VII (Simplicity).

## Language & Tooling

- **Python >= 3.13** required.
- **Package manager:** `uv` (lock file in `uv.lock`).
- **Formatter:** ruff format (line length 150).
- **Linter:** ruff + pylint + yamllint.
- **Type checker:** mypy (strict mode via `pre-commit`).
- Configuration lives in `pyproject.toml` under `[tool.ruff]`,
  `[tool.mypy]`, and `[tool.pylint]`.

## Type Annotations

- All function parameters and return types MUST carry type hints.
- Use `str | None` (not `Optional[str]`).
- Prefer frozen dataclasses or Pydantic models for structured data.
- Avoid `Any` at public interfaces.
- `# type: ignore` MUST include a specific error code:
  `# type: ignore[attr-defined]`.
- For MCP result objects in tests, use
  `# type: ignore[attr-defined]` instead of brittle type assertions.

## Import Organization

- `known-first-party = ["infrahub_mcp"]` (configured in ruff).
- Imports at the top of every file.
- Use `from __future__ import annotations` for forward references.
- Lazy imports (`if TYPE_CHECKING:`) for heavy or circular deps.

## FastMCP Patterns

- **Sub-application mounting:** Each tool/resource/prompt module
  creates its own `FastMCP` instance, mounted onto the main server
  in `server.py`.
- **Middleware composition:** All middleware is composed via
  `configure_middleware(mcp, config)` in `middleware.py`. Never
  attach middleware in individual tool modules.
- **Lifespan context:** Shared state (`InfrahubClient`, `ServerConfig`)
  flows through `AppContext` yielded by `app_lifespan()`.
- **Tool tagging:** Write tools MUST be tagged `"write"` so
  `ReadOnlyMiddleware` can filter them.
- **Error handling:** Raise `ToolError` for user-facing errors.
  Use `McpError` with standard error codes for protocol-level errors.

## Configuration

- `ServerConfig` is a frozen Pydantic `BaseSettings` model loaded
  from `INFRAHUB_MCP_*` environment variables.
- Validation happens at startup via `load_config()`.
- Use `AliasChoices` for fields that accept multiple env var names.
- Use `field_validator` for complex constraints.

## Error Handling

- Raise specific exceptions; avoid bare `except:`.
- Infrahub SDK exceptions (`AuthenticationError`,
  `ServerNotReachableError`, `ServerNotResponsiveError`) MUST be
  caught and translated to MCP-appropriate errors.
- Internal details MUST NOT leak in error messages to clients.

## Docstrings

- Public functions and classes MUST have docstrings.
- Keep docstrings concise — one line for simple functions, a short
  paragraph for complex ones.
- No multi-paragraph docstring blocks unless the function has
  genuinely complex behavior.

## Testing Conventions

- Test files mirror source structure: `tests/test_middleware.py`
  tests `src/infrahub_mcp/middleware.py`.
- Every test is atomic, self-contained, and targets one behavior.
- Use `@pytest.mark.parametrize` for variants.
- Use `pytest-asyncio` for async tests.
- Imports at file top; no dynamic imports inside tests.
- Happy path + key edge cases for each feature.
- Run the full suite: `uv run pytest`.

## Quality Commands

```bash
uv sync                        # Install/update dependencies
uv run pre-commit run          # Format + lint + type check
uv run pytest                  # Full test suite
uv run invoke lint             # All linters
uv run invoke lint-ruff        # Ruff only
uv run invoke lint-mypy        # MyPy only
uv run invoke lint-pylint      # Pylint only
uv run invoke format           # Auto-format
```
