"""Fixtures for the Infrahub MCP integration suite.

Design (see specs/001-infrahub-testcontainers/):
- ONE Infrahub container per pytest session (research D1), provisioned via the
  upstream ``infrahub-testcontainers`` ``InfrahubDockerCompose`` helper used
  directly so we can scope it to the *session* (the upstream ``TestInfrahubDocker``
  fixtures are class-scoped).
- A fresh Infrahub branch per test for isolation (FR-011), deleted on teardown.
- The MCP server is driven via the in-process FastMCP ``Client`` (in-memory
  transport) so the ASGI auth/OIDC layer is bypassed while FastMCP-level
  middleware (ReadOnly, audit, ...) still runs (research D2).

CI runs this suite in the ``python-integration-tests`` job of
``.github/workflows/ci.yml`` (``uv run pytest tests/integration -m integration``).
"""

from __future__ import annotations

import asyncio
import importlib
import os
import subprocess  # noqa: S404 - used only for a local `docker info` probe
import time
import uuid
import warnings
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from fastmcp import Client
from infrahub_sdk import Config, InfrahubClient
from infrahub_testcontainers import __version__ as testcontainers_version
from infrahub_testcontainers.container import PROJECT_ENV_VARIABLES, InfrahubDockerCompose

from tests.integration.fixtures.seed import WIDGET_KIND, seed_baseline

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator

# Well-known initial admin token shipped by infrahub-testcontainers — a fixed
# test fixture, never a production secret.
ADMIN_TOKEN: str = PROJECT_ENV_VARIABLES["INFRAHUB_TESTING_INITIAL_ADMIN_TOKEN"]

#: Set to leave the container running after the suite for inspection (research D8).
KEEP_ENV = "INFRAHUB_TESTCONTAINERS_KEEP"

#: Max seconds to wait for the Infrahub API to answer after the stack starts.
READINESS_TIMEOUT_S = 240

#: Socket the Docker SDK falls back to when ``DOCKER_HOST`` is unset.
DEFAULT_DOCKER_SOCKET = Path("/var/run/docker.sock")

# docker/compose#13899: `up --wait` fails on a project containing a zero-replica
# service, reporting it as a missing dependency. The compose file packaged with
# infrahub-testcontainers declares `task-manager-background-svc` with
# `replicas: ${INFRAHUB_TESTING_TASKMGR_BACKGROUND_SVC_REPLICAS:-0}`, so the
# default trips it on affected Compose versions. One replica is harmless: nothing
# depends on that service. `setdefault` so an explicit value still wins. Same
# workaround as the infrahub-demo-* repositories; drop it once Compose ships the fix.
os.environ.setdefault("INFRAHUB_TESTING_TASKMGR_BACKGROUND_SVC_REPLICAS", "1")


@pytest.fixture(scope="session", autouse=True)
def _disable_dotenv_loading() -> Iterator[None]:
    """Disable ``.env`` probing for the whole suite.

    Unlike the unit tests, these fixtures actually run ``app_lifespan`` with the
    repo root as CWD, so without this a maintainer's own repo-root ``.env`` would
    be primed on top of the credentials set by ``seeded_infrahub`` — permanently,
    since ``os.environ`` mutation is process-wide.
    """
    previous = os.environ.get("INFRAHUB_MCP_ENV_FILE")
    os.environ["INFRAHUB_MCP_ENV_FILE"] = ""
    try:
        yield
    finally:
        if previous is None:
            del os.environ["INFRAHUB_MCP_ENV_FILE"]
        else:
            os.environ["INFRAHUB_MCP_ENV_FILE"] = previous


def _use_docker_cli_context() -> None:
    """Point the Docker SDK at the engine the ``docker`` CLI uses.

    The CLI follows the active Docker context (OrbStack, Colima, Docker Desktop,
    Rancher Desktop); the Python Docker SDK used by testcontainers reads only
    ``DOCKER_HOST`` and otherwise falls back to ``/var/run/docker.sock``. On a Mac
    where that link is missing or points to an engine that is no longer installed,
    ``docker info`` succeeds but the stack fails to start ("Could not register ...
    with Ryuk"). Copy the context's endpoint into ``DOCKER_HOST`` in that case only:
    an explicit ``DOCKER_HOST`` or a working default socket (Linux, CI) is left alone.
    """
    if os.getenv("DOCKER_HOST") or DEFAULT_DOCKER_SOCKET.exists():
        return
    try:
        result = subprocess.run(
            ["docker", "context", "inspect", "--format", "{{.Endpoints.docker.Host}}"],  # noqa: S607 - local docker probe
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return
    host = result.stdout.strip()
    if result.returncode == 0 and host:
        os.environ["DOCKER_HOST"] = host


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ["docker", "info"],  # noqa: S607 - intentional partial path for a local docker probe
            capture_output=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


async def _wait_until_ready(client: InfrahubClient, timeout_s: int = READINESS_TIMEOUT_S) -> None:
    """Poll the Infrahub API until it responds, or fail with a clear timeout (FR-007)."""
    deadline = time.monotonic() + timeout_s
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            await client.get_version()
        except Exception as exc:  # noqa: BLE001 - readiness probe tolerates any transient error
            last_error = exc
            await asyncio.sleep(3)
        else:
            return
    pytest.fail(
        f"Infrahub API did not become ready within {timeout_s}s: {last_error}",
        pytrace=False,
    )


def _make_client(address: str) -> InfrahubClient:
    return InfrahubClient(address=address, config=Config(api_token=ADMIN_TOKEN))


@pytest.fixture(scope="session")
def infrahub_container(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    """Start one Infrahub stack for the whole session; yield its base address.

    Fails fast (no traceback noise) when Docker is unavailable (FR-007, edge:
    Docker-unavailable). Tears the stack down on exit unless ``INFRAHUB_TESTCONTAINERS_KEEP``
    is set (FR-004, edge: Ctrl-C/CI-cancel — pytest finalizers still run).
    """
    _use_docker_cli_context()
    if not _docker_available():
        pytest.fail(
            "Docker engine not reachable — integration tests require Docker. "
            "See specs/001-infrahub-testcontainers/quickstart.md.",
            pytrace=False,
        )

    version = os.getenv("INFRAHUB_TESTING_IMAGE_VER") or testcontainers_version
    directory = Path(tmp_path_factory.mktemp("infrahub"))
    compose = InfrahubDockerCompose.init(directory=directory, version=version)

    try:
        compose.start()
    except Exception as exc:  # noqa: BLE001 - surface compose logs then fail clearly
        stdout, stderr = compose.get_logs()
        pytest.fail(
            f"Failed to start the Infrahub container (image {version}): {exc}\n"
            f"--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}",
            pytrace=False,
        )

    ports = compose.get_services_port()
    address = f"http://localhost:{ports['server']}"

    try:
        yield address
    finally:
        if os.getenv(KEEP_ENV):
            warnings.warn(
                f"{KEEP_ENV} set — leaving Infrahub stack running at {address}. "
                "Tear it down manually with `docker compose ls` + `docker compose -p <project> down -v`.",
                stacklevel=2,
            )
        else:
            compose.stop()


@pytest.fixture(scope="session")
def seeded_infrahub(infrahub_container: str) -> dict[str, object]:
    """Wait for readiness, seed the baseline schema + widgets once, and point the
    MCP server at the container via environment variables (read by ``InfrahubClient()``
    inside the server lifespan, and ``INFRAHUB_MCP_READ_ONLY`` read at server import).

    Returns ``{"address", "widget_kind", "widget_ids"}`` for tests to assert against.
    """

    async def _prepare() -> dict[str, str]:
        client = _make_client(infrahub_container)
        await _wait_until_ready(client)
        return await seed_baseline(client)

    widget_ids = asyncio.run(_prepare())

    os.environ["INFRAHUB_ADDRESS"] = infrahub_container
    os.environ["INFRAHUB_API_TOKEN"] = ADMIN_TOKEN
    # Hard-set (not setdefault): the default mcp_client needs write tools enabled,
    # so any externally-set INFRAHUB_MCP_READ_ONLY=true must be overridden here.
    os.environ["INFRAHUB_MCP_READ_ONLY"] = "false"

    return {"address": infrahub_container, "widget_kind": WIDGET_KIND, "widget_ids": widget_ids}


@pytest.fixture
def infrahub_client(seeded_infrahub: dict[str, object]) -> InfrahubClient:
    """A direct SDK client (admin token) for test-side setup/verification."""
    return _make_client(str(seeded_infrahub["address"]))


@pytest.fixture
async def test_branch(infrahub_client: InfrahubClient) -> AsyncIterator[str]:
    """Create a fresh Infrahub branch off ``main`` for this test; delete on teardown.

    Isolation unit per FR-011 / Constitution III. ``sync_with_git=False`` keeps
    branch creation fast (no repository sync).
    """
    name = f"test-{uuid.uuid4().hex[:8]}"
    await infrahub_client.branch.create(branch_name=name, sync_with_git=False)
    try:
        yield name
    finally:
        await infrahub_client.branch.delete(branch_name=name)


@pytest.fixture
async def mcp_client(seeded_infrahub: dict[str, object]) -> AsyncIterator[Client]:
    """In-process FastMCP client against the server (write tools enabled).

    The server module is imported lazily *after* ``seeded_infrahub`` has set the
    Infrahub env vars and ``INFRAHUB_MCP_READ_ONLY=false`` (read at import time).
    """
    from infrahub_mcp.server import mcp  # noqa: PLC0415 - import after seeded_infrahub sets env

    async with Client(mcp) as client:
        yield client


@pytest.fixture
async def mcp_client_readonly(seeded_infrahub: dict[str, object]) -> AsyncIterator[Client]:
    """In-process FastMCP client with ``read_only=true``.

    RUNTIME: ``read_only`` and write-tool mounting are import-time decisions
    (server.py:49,94,257), so we set the env var and reload the server module to
    rebuild ``mcp`` with ``ReadOnlyMiddleware`` attached and write tools unmounted.
    Confirm reload is clean (module-level FastMCP construction) on first run.
    """
    import infrahub_mcp.server as server_mod  # noqa: PLC0415 - reload after toggling read_only env

    previous = os.environ.get("INFRAHUB_MCP_READ_ONLY", "false")
    os.environ["INFRAHUB_MCP_READ_ONLY"] = "true"
    importlib.reload(server_mod)
    try:
        async with Client(server_mod.mcp) as client:
            yield client
    finally:
        os.environ["INFRAHUB_MCP_READ_ONLY"] = previous
        importlib.reload(server_mod)
