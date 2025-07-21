from pathlib import Path

from invoke import Context, task

CURRENT_DIRECTORY = Path(__file__).resolve()
MAIN_DIRECTORY_PATH = Path(__file__).parent

PYTHON_MODULE = "infrahub_mcp_server"


@task(name="format")
def format_all(context: Context) -> None:
    """Run RUFF to format all Python files."""
    exec_cmds = ["uv run ruff format .", "uv run ruff check . --fix"]
    with context.cd(MAIN_DIRECTORY_PATH):
        for cmd in exec_cmds:
            context.run(cmd, pty=True)


@task
def lint_yaml(context: Context) -> None:
    """Run Linter to check all Python files."""
    print(" - Check code with yamllint")
    exec_cmd = "uv run yamllint -s ."
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd, pty=True)


@task
def lint_mypy(context: Context) -> None:
    """Run Linter to check all Python files."""
    print(" - Check code with mypy")
    exec_cmd = f"uv run mypy --show-error-codes src/{PYTHON_MODULE}"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd, pty=True)


@task
def lint_ruff(context: Context) -> None:
    """Run Linter to check all Python files."""
    print(" - Check code with ruff")
    exec_cmd = "ruff check ."
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd, pty=True)


@task(name="lint")
def lint_all(context: Context) -> None:
    """Run all linters."""
    lint_yaml(context)
    lint_ruff(context)
    lint_mypy(context)
