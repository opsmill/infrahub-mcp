# Quickstart: Running Integration Tests

**Feature**: 001-infrahub-testcontainers
**Audience**: Contributors and maintainers running integration tests locally or debugging CI failures.

## Prerequisites

1. **Docker** engine running and reachable from the shell (`docker info` must succeed).
2. **uv** installed (`uv --version`); project deps synced (`uv sync --all-groups`).
3. **Network egress** to the Infrahub container registry (or a local cache with the pinned image already present).
4. Python 3.13 (managed by `uv`).

If Docker is unavailable, the suite fails fast with: `Docker engine not reachable — integration tests require Docker. See specs/001-infrahub-testcontainers/quickstart.md.`

## Run the full integration suite

```bash
uv run pytest tests/integration
```

Expected: ~3–10 minutes wall clock on a developer machine (image pull on first run accounts for the upper bound). Containers are torn down on exit, including on failure or Ctrl-C.

## Run a single integration test

```bash
uv run pytest tests/integration/test_node_tools.py::test_get_nodes_with_filter -x
```

`-x` stops at first failure (useful while iterating).

## Keep containers running after the suite for inspection

```bash
INFRAHUB_TESTCONTAINERS_KEEP=1 uv run pytest tests/integration/test_graphql_tool.py -x
```

When set, the session fixture skips its `stop()` call so you can `docker compose ls`, find the project name, and poke at the running Infrahub. Remember to tear it down manually with `docker compose -p <project> down -v` when done. The next non-KEEP run starts a brand-new stack.

## Run unit tests only (default — fast loop)

```bash
uv run pytest
```

This continues to behave as before this feature shipped: no Docker, no network, milliseconds-to-seconds total.

## Override the Infrahub image version

The pinned default lives in `pyproject.toml` (`infrahub-testcontainers~=X.Y`). To run against a different Infrahub image (e.g., to reproduce a CI failure on a bumped version):

```bash
INFRAHUB_TESTING_IMAGE_VER=1.10.0 uv run pytest tests/integration
```

This sets the image tag without modifying `pyproject.toml`. Useful for one-off comparisons; permanent bumps go through a normal PR that updates the lockfile.

## Diagnose a CI failure locally

If CI's `integration-tests` job fails:

> **First check:** if the only failure is `test_version_compat` (FR-013), that's **version drift** — the pinned Infrahub image moved outside the range the `infrahub-sdk` supports — not a product regression. Reconcile the `infrahub-testcontainers` / `infrahub-sdk` versions instead of hunting a code bug.

1. Note the Infrahub image version reported in the job's `setup-versions` step.
2. Locally: `INFRAHUB_TESTING_IMAGE_VER=<that version> uv run pytest tests/integration/<failing test>::<name> -x -s`.
3. If the test starts but the assertion fails: read the failure message — it includes the per-test branch name and (on real failure) the last ~200 lines of the `infrahub-server` and `task-worker` container logs.
4. If the test never starts: check Docker (`docker info`), check for port conflicts (lsof on common Infrahub ports), confirm the image pulled.

## Concurrent runs

Two `uv run pytest tests/integration` invocations on the same host work — each gets its own project name, ports, and stack. You'll feel it in Docker memory and CPU first; resource exhaustion will not manifest as a name collision.

## What's *not* covered by integration tests

See [contracts/integration-test-surface.md](./contracts/integration-test-surface.md) for the exact coverage scope. Prompts, OIDC flow, token-passthrough, rate limiting, and caching middleware behavior remain in the unit suite — there is no need to re-run integration to validate those.
