import json
import sys
from pathlib import Path

from invoke import Context, task

from infrahub_mcp.config import ServerConfig

CURRENT_DIRECTORY = Path(__file__).resolve()
DOCUMENTATION_DIRECTORY = CURRENT_DIRECTORY.parent / "docs"

MAIN_DIRECTORY_PATH = Path(__file__).parent


@task(name="format")
def format_all(context: Context) -> None:
    """Run RUFF to format all Python files."""

    exec_cmds = ["uv run ruff format ."]
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
    exec_cmd = "uv run ruff check src/ --fix"
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


EXTRA_ENV_VARS: dict[str, str] = {
    "INFRAHUB_ADDRESS": "http://localhost:8000",
    "INFRAHUB_API_TOKEN": "06438eb2-8019-4776-878c-0941b1f1d1ec",
}

AUTH_MODE_SPECIFIC_FIELDS: set[str] = {
    "oidc_config_url",
    "oidc_client_id",
    "oidc_client_secret",
    "oidc_base_url",
    "oidc_audience",
    "oidc_user_claim",
    "token_passthrough_header",
    "auth_scopes_write",
}

OIDC_ONLY_FIELDS: set[str] = {
    "oidc_config_url",
    "oidc_client_id",
    "oidc_client_secret",
    "oidc_base_url",
    "oidc_audience",
    "oidc_user_claim",
}


def _get_expected_env_vars() -> dict[str, str]:
    """Build the expected {VAR_NAME: default_value} map from ServerConfig + extras."""
    config = ServerConfig()
    env_vars: dict[str, str] = dict(EXTRA_ENV_VARS)

    for field_name in ServerConfig.model_fields:
        if field_name in AUTH_MODE_SPECIFIC_FIELDS:
            continue
        env_name = f"INFRAHUB_MCP_{field_name.upper()}"
        default = getattr(config, field_name)
        if isinstance(default, bool):
            env_vars[env_name] = str(default).lower()
        elif isinstance(default, float) and default == int(default):
            env_vars[env_name] = str(int(default))
        else:
            env_vars[env_name] = str(default) if default is not None else ""

    return env_vars


def _update_docker_compose_env_vars(docker_file: str = "docker-compose.yml") -> None:
    """Regenerate the x-infrahub-mcp-config anchor in docker-compose.yml."""
    docker_path = Path(docker_file)
    lines = docker_path.read_text(encoding="utf-8").splitlines()

    anchor_start: int | None = None
    anchor_end: int | None = None
    for i, line in enumerate(lines):
        if line.strip().startswith("x-infrahub-mcp-config:"):
            anchor_start = i + 1
            continue
        if anchor_start is not None and anchor_end is None and (not line.startswith("  ") or not line.strip()):
            anchor_end = i
            break

    if anchor_start is None or anchor_end is None:
        msg = f"Could not find x-infrahub-mcp-config anchor in {docker_file}"
        raise RuntimeError(msg)

    expected = _get_expected_env_vars()
    new_lines: list[str] = []
    for var in sorted(expected):
        default = expected[var]
        if default:
            new_lines.append(f"  {var}: ${{{var}:-{default}}}")
        else:
            new_lines.append(f"  {var}:")

    lines = lines[:anchor_start] + new_lines + lines[anchor_end:]
    docker_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{docker_file} updated with environment variables")


@task
def gen_config_env(context: Context, update: bool = False) -> None:  # noqa: ARG001
    """Generate list of env vars or update docker-compose.yml."""
    if update:
        _update_docker_compose_env_vars()
    else:
        for var, default in sorted(_get_expected_env_vars().items()):
            print(f"{var}: {default}")


@task
def validate_dockercomposeenv(context: Context) -> None:
    """Validate that docker-compose.yml environment variables are up to date."""
    docker_compose_file = "docker-compose.yml"
    _update_docker_compose_env_vars(docker_compose_file)

    exec_cmd = f"git diff --exit-code {docker_compose_file}"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd)


EXTRA_SERVER_JSON_VARS: set[str] = {
    "INFRAHUB_ADDRESS",
    "INFRAHUB_API_TOKEN",
    "INFRAHUB_USERNAME",
    "INFRAHUB_PASSWORD",
    "INFRAHUB_TIMEOUT",
}

SECRET_ENV_VARS: set[str] = {
    "INFRAHUB_API_TOKEN",
    "INFRAHUB_PASSWORD",
    "INFRAHUB_MCP_OIDC_CLIENT_SECRET",
}


def _get_expected_server_json_vars() -> set[str]:
    """Return the set of INFRAHUB_MCP_* env var names that should appear in server.json.

    Excludes OIDC-only fields (they require auth_mode=oidc and would confuse
    general-purpose registry listings).
    """
    expected: set[str] = set()
    for field_name in ServerConfig.model_fields:
        if field_name in OIDC_ONLY_FIELDS:
            continue
        expected.add(f"INFRAHUB_MCP_{field_name.upper()}")
    return expected


def _validate_server_json(server_json_path: str = "server.json") -> list[str]:
    """Check that server.json environmentVariables covers all non-auth ServerConfig fields.

    Returns a list of error messages (empty if valid).
    """
    path = Path(server_json_path)
    data = json.loads(path.read_text(encoding="utf-8"))

    actual_vars: set[str] = set()
    for pkg in data.get("packages", []):
        actual_vars.update(env_entry["name"] for env_entry in pkg.get("environmentVariables", []))

    expected_mcp_vars = _get_expected_server_json_vars()

    missing = sorted(expected_mcp_vars - actual_vars)
    extra_mcp = sorted(actual_vars - expected_mcp_vars - EXTRA_SERVER_JSON_VARS)

    errors: list[str] = []
    if missing:
        errors.append(f"Missing from server.json: {', '.join(missing)}")
    if extra_mcp:
        errors.append(f"In server.json but not in ServerConfig: {', '.join(extra_mcp)}")
    return errors


@task
def validate_serverjson(context: Context) -> None:  # noqa: ARG001
    """Validate that server.json environment variables match ServerConfig fields."""
    errors = _validate_server_json()
    if errors:
        for err in errors:
            print(f"::error::{err}", file=sys.stderr)
        print(
            "Run 'uv run invoke gen-config-env' to see the expected variables.",
            file=sys.stderr,
        )
        sys.exit(1)
    print("server.json environment variables are in sync with ServerConfig.")


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
            "::error::CAPABILITIES.md is out of date. Run 'uv run invoke update-capabilities' and commit the result.",
            file=sys.stderr,
        )
        sys.exit(1)
