import sys
from pathlib import Path

from invoke import Context, task

CURRENT_DIRECTORY = Path(__file__).resolve()
DOCUMENTATION_DIRECTORY = CURRENT_DIRECTORY.parent / "docs"

MAIN_DIRECTORY_PATH = Path(__file__).parent


@task(name="format")
def format_all(context: Context) -> None:
    """Run RUFF to format all Python files."""

    exec_cmds = ["uv run ruff format .", "uv run ruff check src/ --fix"]
    with context.cd(MAIN_DIRECTORY_PATH):
        for cmd in exec_cmds:
            context.run(cmd)


@task
def lint_yaml(context: Context) -> None:
    """Run Linter to check all Python files."""
    print(" - Check code with yamllint")
    exec_cmd = "uv run yamllint ."
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd)


@task
def lint_mypy(context: Context) -> None:
    """Run Linter to check all Python files."""
    print(" - Check code with mypy")
    exec_cmd = "uv run mypy --show-error-codes src/infrahub_mcp"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd)


@task
def lint_pylint(context: Context) -> None:
    """Run pylint against Emma pages."""
    print(" - Check code with pylint")
    exec_cmd = "uv run pylint src/infrahub_mcp/**/*.py"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd)


@task
def lint_ruff(context: Context) -> None:
    """Run Linter to check all Python files."""
    print(" - Check code with ruff")
    exec_cmd = "uv run ruff check src/"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd)


@task(name="lint")
def lint_all(context: Context) -> None:
    """Run all linters."""
    lint_yaml(context)
    lint_ruff(context)
    lint_mypy(context)
    lint_pylint(context)


@task(name="ui")
def ui_dev(context: Context) -> None:
    """Launch the FastMCP inspector UI for interactive testing (HTTP transport on :6274)."""
    exec_cmd = "uv run fastmcp dev src/infrahub_mcp/server.py:mcp"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd)


@task(name="docs")
def docs_build(context: Context) -> None:
    """Build documentation website."""
    exec_cmd = "npm run build"

    with context.cd(DOCUMENTATION_DIRECTORY):
        output = context.run(exec_cmd)

    if output.exited != 0:
        sys.exit(-1)


@task(name="update-capabilities")
def update_capabilities(context: Context) -> None:
    """Regenerate CAPABILITIES.md from the live MCP server definition.

    Requires the ``mcp-discovery`` CLI on PATH. See scripts/update-capabilities.sh.
    """
    exec_cmd = "bash scripts/update-capabilities.sh CAPABILITIES.md"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd)


@task(name="check-capabilities")
def check_capabilities(context: Context) -> None:
    """Fail if CAPABILITIES.md is stale.

    Regenerates the file into a temp path and diffs against the committed
    CAPABILITIES.md. Non-zero exit signals that a contributor must run
    ``invoke update-capabilities`` and commit the result.
    """
    tmp_path = "/tmp/capabilities-check.md"  # noqa: S108
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(f"bash scripts/update-capabilities.sh {tmp_path}")
        result = context.run(f"diff -u CAPABILITIES.md {tmp_path}", warn=True)
    if result.exited != 0:
        print(
            "::error::CAPABILITIES.md is out of date. "
            "Run 'uv run invoke update-capabilities' and commit the result.",
            file=sys.stderr,
        )
        sys.exit(1)
