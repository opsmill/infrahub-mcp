---
applyTo: '*'
---

# Tooling rules

- Prefer Github Actions for automated validation when user commit to the repository
- Run `uv run pre-commit run` before committing (ruff, mypy on `src/`, rumdl on changed markdown); installing the hook with `uv run pre-commit install` is optional
- Use ruff to lint and format Python files, and ty (CI) and mypy (local) for type checking
- Use yamllint to validate yaml files
- Use uv to manage the python project and its dependencies
