---
applyTo: '**/*.py'
---

# Python Coding Standards

- Use Python 3.10+ syntax and features.
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

The project is using Use ruff and mypy for type checking and validations.

you can format all python files by running `uv run invoke format`
and you can validate that all files are formatted correctly by running `uv run invoke lint`
