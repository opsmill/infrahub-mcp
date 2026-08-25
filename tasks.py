import json
import sys
from pathlib import Path

from invoke import Context, Exit, task

CURRENT_DIRECTORY = Path(__file__).resolve()
DOCUMENTATION_DIRECTORY = CURRENT_DIRECTORY.parent / "docs"

MAIN_DIRECTORY_PATH = Path(__file__).parent

# Directories under docs/ that hold generated or vendored files. They are
# gitignored (see docs/.gitignore), so they never exist in CI's fresh
# checkout — Vale must skip them locally to match CI's file set.
VALE_PRUNED_DIRECTORIES = ("node_modules", "build", ".docusaurus", ".cache-loader")


def _print_skipped_gate(gate: str, remedy: str) -> None:
    """Print an unmissable banner when a CI gate is skipped locally.

    A skipped gate means the run no longer predicts CI, so it must never
    scroll past as an ordinary progress line.
    """
    print()
    print("=" * 78)
    print(f"!! SKIPPED CI GATE: {gate}")
    print(f"!! This run does NOT predict CI. {remedy}")
    print("=" * 78)
    print()


@task(name="format")
def format_all(context: Context) -> None:
    """Run RUFF to format all Python files and apply autofixes.

    Mirrors CI's ``ruff format`` step but with write-mode (CI uses
    ``--check --diff``). The trailing ``ruff check . --fix`` applies
    autofixable lint corrections so a developer running ``invoke format``
    sees a clean tree before invoking the strict ``invoke lint`` gate.
    """
    exec_cmds = [
        "uv run ruff format .",
        "uv run ruff check . --fix",
    ]
    with context.cd(MAIN_DIRECTORY_PATH):
        for cmd in exec_cmds:
            context.run(cmd)


@task
def lint_yaml(context: Context) -> None:
    """Run yamllint in strict mode across the whole tree.

    Mirrors CI's ``yamllint -s .`` step. ``-s`` (strict) treats
    warnings as errors so local runs predict CI exactly.
    """
    print(" - Check code with yamllint")
    exec_cmd = "uv run yamllint -s ."
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
def lint_vale(context: Context) -> None:
    """Run Vale documentation style check across docs/.

    Mirrors CI's ``validate-documentation-style`` job in
    .github/workflows/ci.yml. Requires the ``vale`` binary on PATH
    (``brew install vale``) OR a ``./vale`` binary at the repo root
    (CI installs it there).

    Fails when neither is available. That job is the one CI gate with no
    ``files-changed`` guard — it runs on every pull request, even a
    backend-only one — so silently skipping it locally would turn a green
    ``invoke lint`` into a red CI run.

    CI runs a bare ``find ./docs`` on a freshly checked-out tree, which
    never contains npm dependencies or Docusaurus build output. Locally
    those directories usually *do* exist, and a bare ``find`` sweeps up
    every dependency README under ``docs/node_modules`` (thousands of
    files, none of them ours). Pruning the directories listed in
    ``docs/.gitignore`` makes the local run scan exactly the set CI sees.
    """
    print(" - Check documentation style with vale")
    repo_vale = MAIN_DIRECTORY_PATH / "vale"
    if repo_vale.exists():
        vale_bin = "./vale"
    else:
        from shutil import which  # noqa: PLC0415

        if which("vale") is None:
            msg = (
                "vale binary not found (neither ./vale nor on PATH). CI's "
                "validate-documentation-style job is not path-gated, so it runs on "
                "every pull request and this gate cannot be skipped locally. "
                "Install it with 'brew install vale'."
            )
            raise Exit(msg, code=1)
        vale_bin = "vale"

    prune = " -o ".join(f'-name "{d}"' for d in VALE_PRUNED_DIRECTORIES)
    find_cmd = f'find ./docs \\( {prune} \\) -prune -o -type f \\( -name "*.mdx" -o -name "*.md" \\) -print'
    exec_cmd = f"{find_cmd} | xargs {vale_bin}"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd)


@task
def lint_ty(context: Context) -> None:
    """Run Astral's ``ty`` type checker across the whole tree.

    Mirrors CI's ``ty check .`` step in .github/workflows/ci.yml.
    Local mypy (``invoke lint-mypy``) only checks ``src/infrahub_mcp``,
    so this catches the additional class of errors ty reports against
    tests and project tooling.
    """
    print(" - Check code with ty")
    exec_cmd = "uv run ty check ."
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd)


@task
def lint_ruff(context: Context) -> None:
    """Run ruff check and ruff format --check across the whole tree.

    Mirrors the two ruff steps that CI runs (see ``.github/workflows/ci.yml``):

        uv run ruff check .
        uv run ruff format --check --diff .

    Strict by design — no ``--fix``. Use ``invoke format`` to auto-fix
    formatting and lint issues before running ``invoke lint``.
    """
    print(" - Check code with ruff")
    exec_cmds = [
        "uv run ruff check .",
        "uv run ruff format --check --diff .",
    ]
    with context.cd(MAIN_DIRECTORY_PATH):
        for cmd in exec_cmds:
            context.run(cmd)


@task
def lint_markdown(context: Context) -> None:
    """Run rumdl against the documentation tree.

    Mirrors CI's ``markdown-lint`` job (``uv run rumdl check docs/``).
    Note the scope: CI lints all of ``docs/``, which is wider than the
    ``docs/docs/`` shorthand used for day-to-day authoring, so a finding
    in e.g. ``docs/README.md`` fails CI but not ``rumdl check docs/docs/``.
    """
    print(" - Check markdown with rumdl")
    exec_cmd = "uv run rumdl check docs/"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd)


@task(name="lint")
def lint_all(context: Context) -> None:
    """Run all linters that mirror CI's python-lint, yaml-lint, markdown-lint, and validate-documentation-style jobs."""
    lint_yaml(context)
    lint_ruff(context)
    lint_mypy(context)
    lint_ty(context)
    lint_pylint(context)
    lint_markdown(context)
    lint_vale(context)


@task(name="validate")
def validate_all(context: Context) -> None:
    """Run repo-state validators that mirror CI's validate-* jobs.

    Currently:

    - ``invoke validate-dockercomposeenv`` — checks the
      ``x-infrahub-mcp-config`` anchor in ``docker-compose.yml`` is
      sorted and complete relative to ``ServerConfig``.
    - ``invoke validate-serverjson`` — checks ``server.json`` lists
      every (non-OIDC-only) ``INFRAHUB_MCP_*`` env var.
    - ``invoke check-capabilities`` — checks ``CAPABILITIES.md`` matches the
      live server definition. This one mirrors the ``validate-capabilities``
      job in ``.github/workflows/ci-mcp-discovery.yml``, a *separate*
      workflow that fires on any change under ``src/infrahub_mcp/**``.
      Requires the ``mcp-discovery`` CLI on PATH.
    """
    validate_dockercomposeenv(context)
    validate_serverjson(context)
    check_capabilities(context)


@task(name="ci")
def ci_all(context: Context, docs: bool = True) -> None:
    """Run every CI gate locally — a clean run predicts CI pass/fail.

    Calls in order:

    1. ``invoke lint`` — mirrors CI's ``python-lint`` (ruff check, ruff
       format --check, ty), ``yaml-lint`` (yamllint -s), ``markdown-lint``
       (rumdl check docs/) and ``validate-documentation-style`` (vale)
       jobs, plus mypy, which CI does not run.
    2. ``invoke validate`` — mirrors ``validate-docker-compose-env-vars``
       (docker-compose env vars, server.json env vars) and the
       ``validate-capabilities`` job from ``ci-mcp-discovery.yml``
       (``CAPABILITIES.md`` freshness).
    3. ``invoke docs`` — mirrors the ``documentation`` job (Docusaurus
       build). Needs ``docs/node_modules``; pass ``--no-docs`` to skip it.
    4. ``uv run pytest`` — mirrors ``python-unit-tests``.

    Pull requests also trigger ``ci-mcp-discovery.yml`` whenever
    ``src/infrahub_mcp/**`` changes; its one job is covered by step 2.

    Known divergences from ``.github/workflows/ci.yml``:

    - CI path-gates most jobs off ``files-changed``, so it may skip the
      docs, python or yaml jobs entirely on a given pull request. This
      task runs them unconditionally (except ``--no-docs``), so it is
      stricter than CI, never looser. The one exception in CI is
      ``validate-documentation-style``, which is not path-gated and runs
      on every pull request.
    - CI evaluates the pull request merged with its base branch; this
      task only sees the working tree.
    - ``--no-docs`` drops the ``documentation`` job. The run then prints a
      skipped-gate banner and no longer predicts CI.

    Use ``invoke format`` first to apply autofixes, then ``invoke ci``
    to verify. If CI flags something this task missed, the gap belongs in
    this task — update it and AGENTS.md.
    """
    skipped: list[str] = []

    lint_all(context)
    validate_all(context)

    if docs:
        docs_build(context)
    else:
        skipped.append("documentation (invoke docs)")
        _print_skipped_gate(
            "documentation — the Docusaurus website build",
            "Re-run without --no-docs before pushing anything under docs/.",
        )

    print(" - Run pytest")
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run("uv run pytest")

    if skipped:
        _print_skipped_gate(
            ", ".join(skipped),
            "Green here does NOT mean green in CI.",
        )
    else:
        print(" - All CI gates passed locally")


@task(name="ui")
def ui_dev(context: Context) -> None:
    """Launch the FastMCP inspector UI for interactive testing (HTTP transport on :6274)."""
    exec_cmd = "uv run fastmcp dev src/infrahub_mcp/server.py:mcp"
    with context.cd(MAIN_DIRECTORY_PATH):
        context.run(exec_cmd)


@task(name="docs")
def docs_build(context: Context) -> None:
    """Build documentation website.

    Mirrors CI's ``documentation`` job, which runs this same task inside
    ``docs/``. CI installs the npm dependencies first
    (``pnpm install --frozen-lockfile``); locally they must already be
    present, so a missing ``docs/node_modules`` fails loudly rather than
    letting the gate pass unchecked.
    """
    print(" - Build the documentation website")
    node_modules = DOCUMENTATION_DIRECTORY / "node_modules"
    if not node_modules.is_dir():
        msg = (
            f"{node_modules} is missing, so the docs website build cannot run. "
            "Install the dependencies with 'cd docs && pnpm install --frozen-lockfile', "
            "or run 'invoke ci --no-docs' to skip this gate deliberately."
        )
        raise Exit(msg, code=1)

    exec_cmd = "pnpm run build"

    with context.cd(DOCUMENTATION_DIRECTORY):
        output = context.run(exec_cmd)

    if output is not None and output.exited != 0:
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
    from infrahub_mcp.config import ServerConfig  # noqa: PLC0415

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
    from infrahub_mcp.config import ServerConfig  # noqa: PLC0415

    expected: set[str] = set()
    for field_name in ServerConfig.model_fields:
        if field_name in OIDC_ONLY_FIELDS:
            continue
        expected.add(f"INFRAHUB_MCP_{field_name.upper()}")
    return expected


def _read_server_json(server_json_path: str = "server.json") -> tuple[dict, set[str]]:
    """Read server.json and return (parsed data, set of env var names)."""
    path = Path(server_json_path)
    data = json.loads(path.read_text(encoding="utf-8"))

    actual_vars: set[str] = set()
    for pkg in data.get("packages", []):
        actual_vars.update(env_entry["name"] for env_entry in pkg.get("environmentVariables", []))

    return data, actual_vars


def _check_server_json_drift(actual_vars: set[str]) -> list[str]:
    """Return error messages for env var drift (empty if in sync)."""
    expected_mcp_vars = _get_expected_server_json_vars()

    missing = sorted(expected_mcp_vars - actual_vars)
    extra_mcp = sorted(actual_vars - expected_mcp_vars - EXTRA_SERVER_JSON_VARS)

    errors: list[str] = []
    if missing:
        errors.append(f"Missing from server.json: {', '.join(missing)}")
    if extra_mcp:
        errors.append(f"In server.json but not in ServerConfig: {', '.join(extra_mcp)}")
    return errors


def _get_field_description(field_name: str) -> str:
    """Derive a short description for a ServerConfig field."""
    from infrahub_mcp.config import ServerConfig  # noqa: PLC0415

    config = ServerConfig()
    default = getattr(config, field_name)
    field_info = ServerConfig.model_fields[field_name]

    parts: list[str] = []
    if field_info.description:
        parts.append(field_info.description)
    else:
        parts.append(field_name.replace("_", " ").capitalize())

    if isinstance(default, bool):
        parts.append(f"(default: {str(default).lower()})")
    elif isinstance(default, float) and default == int(default):
        parts.append(f"(default: {int(default)})")
    elif (isinstance(default, str) and default) or isinstance(default, (int, float)):
        parts.append(f"(default: {default})")

    return " ".join(parts)


def _update_server_json(server_json_path: str = "server.json") -> None:
    """Add missing INFRAHUB_MCP_* entries and remove stale ones from server.json."""
    path = Path(server_json_path)
    data, actual_vars = _read_server_json(server_json_path)
    expected_mcp_vars = _get_expected_server_json_vars()

    missing = expected_mcp_vars - actual_vars
    extra_mcp = actual_vars - expected_mcp_vars - EXTRA_SERVER_JSON_VARS

    for pkg in data.get("packages", []):
        env_list: list[dict] = pkg.get("environmentVariables", [])

        if extra_mcp:
            env_list[:] = [e for e in env_list if e["name"] not in extra_mcp]

        for var_name in sorted(missing):
            field_name = var_name.removeprefix("INFRAHUB_MCP_").lower()
            env_list.append(
                {
                    "name": var_name,
                    "description": _get_field_description(field_name),
                    "isRequired": False,
                    "format": "string",
                    "isSecret": var_name in SECRET_ENV_VARS,
                }
            )

    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    if missing or extra_mcp:
        print(f"server.json updated: +{len(missing)} added, -{len(extra_mcp)} removed")
    else:
        print("server.json already up to date")


@task
def validate_serverjson(context: Context, update: bool = False) -> None:  # noqa: ARG001
    """Validate (or update) server.json environment variables against ServerConfig.

    Pass ``--update`` to auto-add missing entries and remove stale ones.
    """
    if update:
        _update_server_json()
        return

    _, actual_vars = _read_server_json()
    errors = _check_server_json_drift(actual_vars)
    if errors:
        for err in errors:
            print(f"::error::{err}", file=sys.stderr)
        print(
            "Run 'uv run invoke validate-serverjson --update' to fix automatically.",
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
    if result is not None and result.exited != 0:
        print(
            "::error::CAPABILITIES.md is out of date. Run 'uv run invoke update-capabilities' and commit the result.",
            file=sys.stderr,
        )
        sys.exit(1)
