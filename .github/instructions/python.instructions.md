---
applyTo: '**/*.py'
---

# Python Coding Standards

- Use Python 3.13+ syntax and features (the project requires Python 3.13).
- Follow PEP 8 for code style and formatting.
- Use type annotations for all function signatures and variables.
- Prefer f-strings for string formatting.
- Avoid wildcard imports; import only what you need.
- Organize imports using `ruff` or `isort` conventions: standard library, third-party, local.
- Write small, single-responsibility functions and classes.
- Avoid global variables; prefer dependency injection or class attributes.
- Use context managers (`with` statements) for resource management.
- Prefer list comprehensions and generator expressions over manual loops when appropriate.
- Use built-in exceptions or define custom exceptions for error handling.
- Document all public modules, classes, and functions.

## Formatting and Linting

The project uses ruff for formatting and linting, and ty (in CI) and mypy (locally, on `src/`) for type checking.

Format all Python files with `uv run invoke format`. Before pushing, run the same checks as CI:
`uv run ruff check .`, `uv run ruff format --check .` and `uv run ty check .`. `uv run invoke lint` runs yamllint, ruff and mypy on `src/`, and pylint.
