"""Tests for the hash-validated schema cache (``schema_cache.py``).

This file mocks the SDK's ``InfrahubClient._get`` private method extensively
because the schema-cache module deliberately calls it to reach the
``GET /api/schema/summary`` endpoint that the SDK does not yet wrap publicly.
The file-level ``ruff: noqa: SLF001`` is therefore intentional.
"""

# ruff: noqa: SLF001

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, NoReturn
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware.caching import (
    CallToolSettings,
    ListPromptsSettings,
    ListResourcesSettings,
    ListToolsSettings,
    ReadResourceSettings,
)
from infrahub_sdk.exceptions import AuthenticationError, BranchNotFoundError, SchemaNotFoundError

from infrahub_mcp import schema_cache
from infrahub_mcp.config import ServerConfig
from infrahub_mcp.middleware import (
    MetricsMiddleware,
    _build_response_caching_middleware,
    _SchemaAwareResponseCachingMiddleware,
)
from infrahub_mcp.schema import get_schema_catalog
from infrahub_mcp.schema_cache import (
    CachedSchemaEntry,
    _BranchGoneError,
    get_cached_branch_schema,
    get_cached_graphql_sdl,
    get_cached_kind,
)
from infrahub_mcp.utils import AppContext

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_branch_schema(*, schema_hash: str, kinds: list[str] | None = None) -> MagicMock:
    """Build a MagicMock that quacks like ``BranchSchema``."""
    schema = MagicMock(name=f"BranchSchema(hash={schema_hash})")
    schema.hash = schema_hash
    schema.nodes = {}
    for kind in kinds or []:
        kind_obj = MagicMock(name=f"NodeSchema({kind})")
        kind_obj.kind = kind
        schema.nodes[kind] = kind_obj
    return schema


def _make_response(*, status_code: int = 200, json_body: dict[str, Any] | None = None, text: str = "") -> MagicMock:
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = json_body or {}
    response.text = text
    response.raise_for_status = MagicMock()
    if status_code >= 400 and status_code != httpx.codes.NOT_FOUND:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "boom",
            request=MagicMock(),
            response=response,
        )
    return response


# Statuses ``/api/schema/summary`` answers for a deleted branch. Infrahub raises
# ``BranchNotFoundError`` with ``HTTP_CODE = 400`` from the branch dependency,
# so 400 is the real-world code; 404 is kept as the generic not-found signal.
_BRANCH_GONE_PARAMS = [
    pytest.param(httpx.codes.BAD_REQUEST, id="400-infrahub-BranchNotFoundError"),
    pytest.param(httpx.codes.NOT_FOUND, id="404-not-found"),
]


def _make_config(**overrides: Any) -> ServerConfig:
    """Build a ServerConfig with defaults safe for tests (caching enabled, generous thresholds)."""
    defaults: dict[str, Any] = {
        "schema_cache_enabled": True,
        "schema_cache_ttl": 30,
        "schema_cache_max_consecutive_failures": 10,
        "schema_cache_max_staleness_seconds": 900,
        "auth_mode": "none",
    }
    defaults.update(overrides)
    return ServerConfig(**defaults)


def _make_client() -> MagicMock:
    """Build an ``InfrahubClient`` mock whose SDK schema cache behaves like the real one.

    ``schema.cache`` is a real dict and ``schema.set_cache`` writes into it, so
    the ``schema_cache_enabled=False`` path — which reads that cache before
    fetching — sees the same hit/miss behaviour the SDK provides.
    """
    client = MagicMock()
    client.address = "http://infrahub.test"
    client.schema = MagicMock()
    client.schema.cache = {}
    client.schema._fetch = AsyncMock()
    client.schema.get_graphql_schema = AsyncMock(return_value="sdl")
    client.schema.set_cache = MagicMock(
        side_effect=lambda schema, branch: client.schema.cache.__setitem__(branch, schema)
    )
    client._get = AsyncMock()
    return client


@pytest.fixture
def mock_client() -> MagicMock:
    return _make_client()


@pytest.fixture
def app_ctx() -> AppContext:
    return AppContext(client=None, config=_make_config(), default_branch="main")


@pytest.fixture
def mock_ctx(app_ctx: AppContext) -> MagicMock:
    ctx = MagicMock()
    ctx.request_context = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    return ctx


@pytest.fixture(autouse=True)
def _patch_dependencies(mock_client: MagicMock, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch get_client and get_default_branch globally for the test module."""
    monkeypatch.setattr(schema_cache, "get_client", lambda _ctx: mock_client)

    async def fake_default_branch(_ctx: Any) -> str:  # noqa: RUF029  # async signature required by production contract
        return "main"

    monkeypatch.setattr(schema_cache, "get_default_branch", fake_default_branch)
    return mock_client


@pytest.fixture
def mock_metrics(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    metrics = MagicMock()
    metrics.record_schema_cache_event = MagicMock()
    monkeypatch.setattr(schema_cache, "_get_metrics", lambda: metrics)
    return metrics


# ---------------------------------------------------------------------------
# US1 — Fast schema reads
# ---------------------------------------------------------------------------


class TestUS1ColdAndWarm:
    @pytest.mark.anyio
    async def test_cold_fetch_populates_cache(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        mock_metrics: MagicMock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1", kinds=["InfraDevice"])
        mock_client.schema._fetch.return_value = schema
        mock_client.schema.get_graphql_schema.return_value = "schema { Query }"

        result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        assert "main" in app_ctx.schema_cache
        assert app_ctx.schema_cache["main"].schema_hash == "H1"
        mock_client.schema._fetch.assert_awaited_once_with(branch="main")
        mock_client.schema.set_cache.assert_called_once_with(schema=schema, branch="main")
        mock_metrics.record_schema_cache_event.assert_any_call("miss")

    @pytest.mark.anyio
    async def test_warm_cache_within_skip_window_no_upstream_call(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        mock_metrics: MagicMock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=schema_cache._now(),
            consecutive_failures=0,
        )

        result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        mock_client.schema._fetch.assert_not_awaited()
        mock_client._get.assert_not_awaited()
        mock_metrics.record_schema_cache_event.assert_any_call("hit")

    @pytest.mark.anyio
    async def test_disabled_flag_bypasses_cache(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        app_ctx.config = _make_config(schema_cache_enabled=False)
        schema = _make_branch_schema(schema_hash="H1")
        mock_client.schema._fetch.return_value = schema

        result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        assert "main" not in app_ctx.schema_cache  # process-wide cache untouched
        assert mock_client.schema.cache["main"] is schema  # SDK per-client cache primed
        mock_client.schema._fetch.assert_awaited_once_with(branch="main")


class TestDisabledFlagUsesSdkCache:
    """``schema_cache_enabled=False`` must reproduce the pre-feature baseline.

    Pre-feature, tools called ``client.schema.all()`` / ``get()``, which cache
    per client for the process lifetime. The disabled path must not regress
    that into a fetch per call on the shared lifespan client.
    """

    @pytest.mark.anyio
    async def test_shared_client_fetches_once_then_serves_from_sdk_cache(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        app_ctx.config = _make_config(schema_cache_enabled=False)
        schema = _make_branch_schema(schema_hash="H1")
        mock_client.schema._fetch.return_value = schema

        first = await get_cached_branch_schema(mock_ctx)
        second = await get_cached_branch_schema(mock_ctx)

        assert first is schema
        assert second is schema
        mock_client.schema._fetch.assert_awaited_once_with(branch="main")
        mock_client.schema.set_cache.assert_called_once_with(schema=schema, branch="main")

    @pytest.mark.anyio
    async def test_fresh_client_per_request_fetches_once_per_call(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Passthrough shape: a new client per request has an empty SDK cache each time."""
        app_ctx.config = _make_config(schema_cache_enabled=False)
        schema = _make_branch_schema(schema_hash="H1")
        clients = [_make_client(), _make_client()]
        for client in clients:
            client.schema._fetch.return_value = schema
        remaining = iter(clients)
        monkeypatch.setattr(schema_cache, "get_client", lambda _ctx: next(remaining))

        first = await get_cached_branch_schema(mock_ctx)
        second = await get_cached_branch_schema(mock_ctx)

        assert first is schema
        assert second is schema
        for client in clients:
            client.schema._fetch.assert_awaited_once_with(branch="main")
            assert client.schema.cache["main"] is schema

    @pytest.mark.anyio
    async def test_present_kind_costs_one_fetch_and_no_sdk_get(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        app_ctx.config = _make_config(schema_cache_enabled=False)
        schema = _make_branch_schema(schema_hash="H1", kinds=["InfraDevice"])
        mock_client.schema._fetch.return_value = schema
        mock_client.schema.get = AsyncMock()

        first = await get_cached_kind(mock_ctx, kind="InfraDevice")
        second = await get_cached_kind(mock_ctx, kind="InfraDevice")

        assert first is schema.nodes["InfraDevice"]
        assert second is schema.nodes["InfraDevice"]
        mock_client.schema._fetch.assert_awaited_once_with(branch="main")
        mock_client.schema.get.assert_not_awaited()


class TestSingleFlight:
    @pytest.mark.anyio
    async def test_concurrent_cold_fetch_results_in_one_upstream_call(
        self,
        mock_ctx: MagicMock,
        mock_client: MagicMock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")

        slow_event = asyncio.Event()
        call_count = 0

        async def slow_fetch(branch: str) -> Any:
            nonlocal call_count
            call_count += 1
            await slow_event.wait()
            return schema

        mock_client.schema._fetch.side_effect = slow_fetch

        async def runner() -> Any:
            return await get_cached_branch_schema(mock_ctx)

        tasks = [asyncio.create_task(runner()) for _ in range(10)]
        await asyncio.sleep(0)  # let all coroutines park on the lock
        slow_event.set()
        results = await asyncio.gather(*tasks)

        assert all(r is schema for r in results)
        assert call_count == 1, f"expected exactly one upstream fetch under burst, got {call_count}"


# ---------------------------------------------------------------------------
# US2 — Hash-validated revalidation
# ---------------------------------------------------------------------------


class TestUS2Revalidation:
    @pytest.mark.anyio
    async def test_past_skip_window_hash_match_extends_cache(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        mock_metrics: MagicMock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        old_time = schema_cache._now() - 100  # past skip-window, under staleness ceiling
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=old_time,
            consecutive_failures=0,
        )
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})

        result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        mock_client.schema._fetch.assert_not_awaited()
        assert app_ctx.schema_cache["main"].fetched_at_monotonic > old_time
        mock_metrics.record_schema_cache_event.assert_any_call("hash_match")

    @pytest.mark.anyio
    async def test_past_skip_window_hash_diff_triggers_full_refetch(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        mock_metrics: MagicMock,
    ) -> None:
        old_schema = _make_branch_schema(schema_hash="H1")
        new_schema = _make_branch_schema(schema_hash="H2", kinds=["NewKind"])
        old_time = schema_cache._now() - 100  # past skip-window, under staleness ceiling
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=old_schema,
            schema_hash="H1",
            graphql_sdl="old-sdl",
            fetched_at_monotonic=old_time,
            consecutive_failures=0,
        )

        # client._get only carries /api/schema/summary; the SDL uses the SDK method.
        mock_client._get.return_value = _make_response(json_body={"main": "H2"})
        mock_client.schema.get_graphql_schema.return_value = "new-sdl"
        mock_client.schema._fetch.return_value = new_schema

        result = await get_cached_branch_schema(mock_ctx)

        assert result is new_schema
        assert app_ctx.schema_cache["main"].schema_hash == "H2"
        assert app_ctx.schema_cache["main"].graphql_sdl == "new-sdl"
        mock_client.schema._fetch.assert_awaited_once()
        mock_metrics.record_schema_cache_event.assert_any_call("hash_diff")

    @pytest.mark.anyio
    @pytest.mark.parametrize("status_code", _BRANCH_GONE_PARAMS)
    async def test_branch_gone_evicts_entry(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        status_code: int,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        old_time = schema_cache._now() - 100  # past skip-window, under staleness ceiling
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=old_time,
            consecutive_failures=0,
        )
        mock_client._get.return_value = _make_response(status_code=status_code)

        # The private _BranchGoneError is translated at the eviction site, so
        # callers see the same public error a cold cache miss produces (the SDK
        # raises BranchNotFoundError from /api/schema on an unknown branch).
        # Infrahub answers a deleted branch with 400, not 404, so both must
        # evict; a 400 must never be recorded as a transient failure.
        with pytest.raises(BranchNotFoundError):
            await get_cached_branch_schema(mock_ctx)

        assert "main" not in app_ctx.schema_cache

    @pytest.mark.anyio
    @pytest.mark.parametrize("status_code", _BRANCH_GONE_PARAMS)
    async def test_branch_gone_does_not_leak_private_error(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        status_code: int,
    ) -> None:
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=_make_branch_schema(schema_hash="H1"),
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=schema_cache._now() - 100,
            consecutive_failures=0,
        )
        mock_client._get.return_value = _make_response(status_code=status_code)

        with pytest.raises(BranchNotFoundError) as excinfo:
            await get_cached_graphql_sdl(mock_ctx)

        assert not isinstance(excinfo.value, _BranchGoneError)
        assert excinfo.value.identifier == "main"

    @pytest.mark.anyio
    async def test_summary_url_encodes_branch_name(self, mock_client: MagicMock) -> None:
        # Infrahub's branch-name validator allows ``#``, ``&``, ``=`` and ``/``.
        # Interpolated raw, ``#`` would drop the query as a fragment and ``&``
        # would split it, so ``/summary`` would answer for the default branch
        # and its hash be compared against this branch's cache entry.
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})

        result = await schema_cache._fetch_summary_hash(mock_client, "fix#123&x=y/sub")

        assert result == "H1"
        mock_client._get.assert_awaited_once_with(
            url="http://infrahub.test/api/schema/summary?branch=fix%23123%26x%3Dy%2Fsub"
        )


class TestUS2LazyOnMissingKind:
    @pytest.mark.anyio
    async def test_kind_present_returns_immediately(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1", kinds=["InfraDevice"])
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=schema_cache._now(),
            consecutive_failures=0,
        )

        kind = await get_cached_kind(mock_ctx, kind="InfraDevice")

        assert kind is schema.nodes["InfraDevice"]
        mock_client.schema._fetch.assert_not_awaited()

    @pytest.mark.anyio
    async def test_missing_kind_with_unchanged_hash_propagates_not_found(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1", kinds=["InfraDevice"])
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=schema_cache._now(),
            consecutive_failures=0,
        )

        # Missing kind triggers force_revalidate path: /summary returns same hash,
        # so no full refetch — schema stays the same — kind still missing.
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})

        with pytest.raises(SchemaNotFoundError):
            await get_cached_kind(mock_ctx, kind="GhostKind")

        # Full schema fetch should NOT have been called (hash matched).
        mock_client.schema._fetch.assert_not_awaited()

    @pytest.mark.anyio
    async def test_missing_kind_with_changed_hash_refetches_and_returns(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        old_schema = _make_branch_schema(schema_hash="H1", kinds=["InfraDevice"])
        new_schema = _make_branch_schema(schema_hash="H2", kinds=["InfraDevice", "NewKind"])
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=old_schema,
            schema_hash="H1",
            graphql_sdl="old-sdl",
            fetched_at_monotonic=schema_cache._now(),
            consecutive_failures=0,
        )

        mock_client._get.return_value = _make_response(json_body={"main": "H2"})
        mock_client.schema.get_graphql_schema.return_value = "new-sdl"
        mock_client.schema._fetch.return_value = new_schema

        kind = await get_cached_kind(mock_ctx, kind="NewKind")

        assert kind is new_schema.nodes["NewKind"]
        mock_client.schema._fetch.assert_awaited_once()


class _FakeClock:
    """Controllable stand-in for ``schema_cache._now``."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    fake = _FakeClock()
    monkeypatch.setattr(schema_cache, "_now", lambda: fake.now)
    return fake


def _entry(
    schema: MagicMock,
    *,
    fetched_at_monotonic: float,
    last_attempt_monotonic: float,
    consecutive_failures: int = 0,
) -> CachedSchemaEntry:
    """A warm ``main`` entry with explicit success and attempt timestamps."""
    return CachedSchemaEntry(
        branch="main",
        schema=schema,
        schema_hash="H1",
        graphql_sdl="sdl",
        fetched_at_monotonic=fetched_at_monotonic,
        consecutive_failures=consecutive_failures,
        last_attempt_monotonic=last_attempt_monotonic,
    )


class TestForcedRevalidationDebounce:
    """A kind miss bypasses the skip-window, not the probe budget.

    Before the debounce every miss probed ``/summary`` under the cache lock,
    so a tool call resolving several unknown kinds — or a burst of misses for
    a mistyped kind — paid one round-trip per kind even though the first had
    just proved the cache current.
    """

    @pytest.mark.anyio
    async def test_misses_within_the_debounce_share_one_probe(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        clock: _FakeClock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1", kinds=["InfraDevice"])
        app_ctx.schema_cache["main"] = _entry(
            schema, fetched_at_monotonic=clock.now - 10, last_attempt_monotonic=clock.now - 10
        )
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})

        with pytest.raises(SchemaNotFoundError):
            await get_cached_kind(mock_ctx, kind="GhostKind")
        clock.advance(1)
        with pytest.raises(SchemaNotFoundError):
            await get_cached_kind(mock_ctx, kind="OtherGhost")

        mock_client._get.assert_awaited_once()  # the second miss reused the first probe
        mock_client.schema._fetch.assert_not_awaited()

    @pytest.mark.anyio
    async def test_miss_past_the_debounce_probes_again(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        clock: _FakeClock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1", kinds=["InfraDevice"])
        app_ctx.schema_cache["main"] = _entry(
            schema, fetched_at_monotonic=clock.now - 10, last_attempt_monotonic=clock.now - 10
        )
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})

        with pytest.raises(SchemaNotFoundError):
            await get_cached_kind(mock_ctx, kind="GhostKind")
        clock.advance(schema_cache._FORCED_REVALIDATE_DEBOUNCE_SECONDS)
        with pytest.raises(SchemaNotFoundError):
            await get_cached_kind(mock_ctx, kind="GhostKind")

        assert mock_client._get.await_count == 2

    @pytest.mark.anyio
    async def test_kind_added_upstream_is_found_on_the_first_miss_past_the_debounce(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        clock: _FakeClock,
    ) -> None:
        """The case the forced probe exists for survives the debounce, well inside the skip-window."""
        old_schema = _make_branch_schema(schema_hash="H1", kinds=["InfraDevice"])
        new_schema = _make_branch_schema(schema_hash="H2", kinds=["InfraDevice", "NewKind"])
        # Populated just now: the attempt that populated it is inside the debounce.
        app_ctx.schema_cache["main"] = _entry(
            old_schema, fetched_at_monotonic=clock.now, last_attempt_monotonic=clock.now
        )
        mock_client._get.return_value = _make_response(json_body={"main": "H2"})
        mock_client.schema._fetch.return_value = new_schema

        clock.advance(1)
        with pytest.raises(SchemaNotFoundError):  # debounced: served as-is, no probe yet
            await get_cached_kind(mock_ctx, kind="NewKind")
        mock_client._get.assert_not_awaited()

        clock.advance(schema_cache._FORCED_REVALIDATE_DEBOUNCE_SECONDS)  # still 27 s inside the skip-window
        kind = await get_cached_kind(mock_ctx, kind="NewKind")

        assert kind is new_schema.nodes["NewKind"]
        mock_client._get.assert_awaited_once()
        mock_client.schema._fetch.assert_awaited_once()

    @pytest.mark.anyio
    async def test_concurrent_misses_behind_one_probe_share_it(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        clock: _FakeClock,
    ) -> None:
        """``schema.py`` gathers ``get_cached_kind`` over a kind's peers: one probe for the whole fan-out."""
        schema = _make_branch_schema(schema_hash="H1", kinds=["InfraDevice"])
        app_ctx.schema_cache["main"] = _entry(
            schema, fetched_at_monotonic=clock.now - 10, last_attempt_monotonic=clock.now - 10
        )
        release = asyncio.Event()

        async def slow_summary(*_args: object, **_kwargs: object) -> MagicMock:
            await release.wait()
            return _make_response(json_body={"main": "H1"})

        mock_client._get.side_effect = slow_summary

        async def miss(kind: str) -> str | None:
            try:
                await get_cached_kind(mock_ctx, kind=kind)
            except SchemaNotFoundError:
                return kind
            return None

        tasks = [asyncio.create_task(miss(f"Ghost{i}")) for i in range(5)]
        await asyncio.sleep(0)  # park every miss on the lock behind the first probe
        release.set()
        results = await asyncio.gather(*tasks)

        assert results == [f"Ghost{i}" for i in range(5)]
        assert mock_client._get.await_count == 1, (
            f"expected one probe for the fan-out, got {mock_client._get.await_count}"
        )

    @pytest.mark.anyio
    async def test_miss_honours_the_failure_throttle(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        clock: _FakeClock,
    ) -> None:
        """A missing kind says nothing about upstream health: no re-probe inside the throttle window."""
        schema = _make_branch_schema(schema_hash="H1", kinds=["InfraDevice"])
        app_ctx.schema_cache["main"] = _entry(
            schema,
            fetched_at_monotonic=clock.now - 100,  # past the skip-window
            consecutive_failures=1,
            last_attempt_monotonic=clock.now - 5,  # failed probe: past the debounce, inside the 30 s throttle
        )
        mock_client._get.side_effect = httpx.NetworkError("down")

        with pytest.raises(SchemaNotFoundError):
            await get_cached_kind(mock_ctx, kind="GhostKind")

        mock_client._get.assert_not_awaited()
        assert app_ctx.schema_cache["main"].consecutive_failures == 1

    @pytest.mark.anyio
    async def test_forced_read_on_a_tripped_entry_fails_fast_inside_the_throttle(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        clock: _FakeClock,
    ) -> None:
        """The breaker's fail-fast applies to forced reads too; before, they probed regardless."""
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = _entry(
            schema,
            fetched_at_monotonic=clock.now - 100,
            consecutive_failures=10,  # tripped
            last_attempt_monotonic=clock.now - 5,
        )
        mock_client._get.side_effect = httpx.NetworkError("down")

        with pytest.raises(ToolError, match="circuit-break"):
            await schema_cache._ensure_entry(ctx=mock_ctx, branch=None, force_revalidate=True)

        mock_client._get.assert_not_awaited()


# ---------------------------------------------------------------------------
# US3 — Resilience
# ---------------------------------------------------------------------------


class TestUS3Resilience:
    @pytest.mark.anyio
    async def test_summary_failure_serves_stale_and_increments_counter(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        mock_metrics: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        old_time = schema_cache._now() - 100  # past skip-window, under staleness ceiling
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=old_time,
            consecutive_failures=2,
        )
        mock_client._get.side_effect = httpx.NetworkError("boom")

        with caplog.at_level("WARNING", logger="infrahub_mcp.schema_cache"):
            result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        assert app_ctx.schema_cache["main"].consecutive_failures == 3
        # Stale schema/hash preserved.
        assert app_ctx.schema_cache["main"].schema_hash == "H1"
        mock_metrics.record_schema_cache_event.assert_any_call("revalidate_failure")
        assert any("schema_cache_revalidate_failure" in r.message for r in caplog.records)

    @pytest.mark.anyio
    async def test_refetch_failure_serves_stale_after_hash_diff(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        mock_metrics: MagicMock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        old_time = schema_cache._now() - 100  # past skip-window, under staleness ceiling
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=old_time,
            consecutive_failures=0,
        )
        mock_client._get.return_value = _make_response(json_body={"main": "H2"})
        mock_client.schema._fetch.side_effect = httpx.NetworkError("refetch-boom")

        result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        assert app_ctx.schema_cache["main"].consecutive_failures == 1
        assert app_ctx.schema_cache["main"].schema_hash == "H1"
        mock_metrics.record_schema_cache_event.assert_any_call("revalidate_failure")

    @pytest.mark.anyio
    async def test_cold_fetch_failure_bubbles(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        mock_client.schema._fetch.side_effect = httpx.NetworkError("boom")

        with pytest.raises(httpx.NetworkError):
            await get_cached_branch_schema(mock_ctx)

        assert "main" not in app_ctx.schema_cache


# ---------------------------------------------------------------------------
# Probe throttling from the first failure — before the breaker trips, and cold
# ---------------------------------------------------------------------------


def _past_window_entry(
    schema: MagicMock,
    *,
    now: float,
    consecutive_failures: int = 0,
    last_attempt_monotonic: float = 0.0,
) -> CachedSchemaEntry:
    """A warm ``main`` entry past the 30 s skip-window but well under the staleness ceiling."""
    return CachedSchemaEntry(
        branch="main",
        schema=schema,
        schema_hash="H1",
        graphql_sdl="sdl",
        fetched_at_monotonic=now - 100,
        consecutive_failures=consecutive_failures,
        last_attempt_monotonic=last_attempt_monotonic,
    )


def _slow_failure(release: asyncio.Event) -> Callable[..., Awaitable[NoReturn]]:
    """Upstream stub that hangs until *release* is set, then fails — one simulated timeout."""

    async def upstream(*_args: object, **_kwargs: object) -> NoReturn:
        await release.wait()
        msg = "down"
        raise httpx.NetworkError(msg)

    return upstream


class TestFailureThrottle:
    """A failing branch costs one upstream timeout per window, not one per request.

    The throttle arms on the first failed probe, whatever the breaker state;
    before this, every read past the skip-window serialized on the cache lock
    behind its own upstream timeout until the failure count reached the
    threshold, and a cold cache never self-limited at all.
    """

    @pytest.mark.anyio
    async def test_failed_probe_serves_stale_without_reprobing_within_window(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        mock_metrics: MagicMock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = _past_window_entry(schema, now=schema_cache._now())
        mock_client._get.side_effect = httpx.NetworkError("down")

        first = await get_cached_branch_schema(mock_ctx)
        second = await get_cached_branch_schema(mock_ctx)

        assert first is schema
        assert second is schema
        mock_client._get.assert_awaited_once()  # the second read did not go upstream
        assert app_ctx.schema_cache["main"].consecutive_failures == 1
        events = [c.args[0] for c in mock_metrics.record_schema_cache_event.call_args_list]
        assert events.count("revalidate_failure") == 1
        assert events.count("stale_hit") == 1

    @pytest.mark.anyio
    async def test_probe_resumes_once_the_window_has_elapsed(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        now = schema_cache._now()
        app_ctx.schema_cache["main"] = _past_window_entry(
            schema,
            now=now,
            consecutive_failures=1,
            last_attempt_monotonic=now - 31,  # window is min(ttl=30, 30)
        )
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})

        result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        mock_client._get.assert_awaited_once()
        assert app_ctx.schema_cache["main"].consecutive_failures == 0

    @pytest.mark.anyio
    async def test_only_a_failed_attempt_arms_the_throttle(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        """A recent *successful* attempt is governed by the skip-window alone."""
        schema = _make_branch_schema(schema_hash="H1")
        now = schema_cache._now()
        app_ctx.schema_cache["main"] = _past_window_entry(
            schema,
            now=now,
            consecutive_failures=0,
            last_attempt_monotonic=now,  # recent, but not a failure
        )
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})

        await get_cached_branch_schema(mock_ctx)

        mock_client._get.assert_awaited_once()

    @pytest.mark.anyio
    async def test_ttl_zero_disables_the_throttle(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        app_ctx.config = _make_config(schema_cache_ttl=0)
        schema = _make_branch_schema(schema_hash="H1")
        now = schema_cache._now()
        app_ctx.schema_cache["main"] = _past_window_entry(
            schema,
            now=now,
            consecutive_failures=1,
            last_attempt_monotonic=now,  # probe just failed
        )
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})

        await get_cached_branch_schema(mock_ctx)

        mock_client._get.assert_awaited_once()

    @pytest.mark.anyio
    async def test_burst_behind_a_failing_probe_costs_one_upstream_timeout(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        """Twenty concurrent reads during an outage, breaker not yet tripped: one probe, all served stale."""
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = _past_window_entry(schema, now=schema_cache._now())
        release = asyncio.Event()
        mock_client._get.side_effect = _slow_failure(release)

        tasks = [asyncio.create_task(get_cached_branch_schema(mock_ctx)) for _ in range(20)]
        await asyncio.sleep(0)  # park every waiter on the lock behind the first probe
        release.set()
        results = await asyncio.gather(*tasks)

        assert all(r is schema for r in results)
        assert mock_client._get.await_count == 1, (
            f"expected one probe for the burst, got {mock_client._get.await_count}"
        )
        assert app_ctx.schema_cache["main"].consecutive_failures == 1

    @pytest.mark.anyio
    async def test_cold_fetch_failure_fails_fast_within_the_window(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        mock_client.schema._fetch.side_effect = httpx.NetworkError("down")

        with caplog.at_level("WARNING", logger="infrahub_mcp.schema_cache"), pytest.raises(httpx.NetworkError):
            await get_cached_branch_schema(mock_ctx)
        with pytest.raises(ToolError, match=r"temporarily unavailable.*next upstream attempt"):
            await get_cached_branch_schema(mock_ctx)

        mock_client.schema._fetch.assert_awaited_once()  # the second read never went upstream
        assert "main" in app_ctx.schema_cache_cold_failures
        assert "main" not in app_ctx.schema_cache
        assert any("schema_cache_cold_fetch_failure" in r.message for r in caplog.records)

    @pytest.mark.anyio
    async def test_cold_fetch_retries_after_the_window_and_a_success_clears_the_marker(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        app_ctx.schema_cache_cold_failures["main"] = schema_cache._now() - 31  # window is min(ttl=30, 30)
        mock_client.schema._fetch.side_effect = httpx.NetworkError("still down")

        # Past the window: the read probes again; a repeat failure re-arms the throttle.
        with pytest.raises(httpx.NetworkError):
            await get_cached_branch_schema(mock_ctx)
        with pytest.raises(ToolError, match="temporarily unavailable"):
            await get_cached_branch_schema(mock_ctx)
        assert mock_client.schema._fetch.await_count == 1

        # Upstream heals: the next probe past the window succeeds and clears the marker.
        app_ctx.schema_cache_cold_failures["main"] = schema_cache._now() - 31
        schema = _make_branch_schema(schema_hash="H1")
        mock_client.schema._fetch.side_effect = None
        mock_client.schema._fetch.return_value = schema

        result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        assert mock_client.schema._fetch.await_count == 2
        assert "main" not in app_ctx.schema_cache_cold_failures
        assert app_ctx.schema_cache["main"].schema is schema

    @pytest.mark.anyio
    async def test_cold_burst_behind_a_failing_fetch_costs_one_upstream_timeout(
        self,
        mock_ctx: MagicMock,
        mock_client: MagicMock,
    ) -> None:
        """Twenty concurrent cold reads during an outage: one fetch, the rest fail fast."""
        release = asyncio.Event()
        mock_client.schema._fetch.side_effect = _slow_failure(release)

        tasks = [asyncio.create_task(get_cached_branch_schema(mock_ctx)) for _ in range(20)]
        await asyncio.sleep(0)  # park every waiter on the lock behind the first fetch
        release.set()
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        assert mock_client.schema._fetch.await_count == 1, (
            f"expected one cold fetch for the burst, got {mock_client.schema._fetch.await_count}"
        )
        assert sum(isinstance(o, httpx.NetworkError) for o in outcomes) == 1  # the read that probed
        assert sum(isinstance(o, ToolError) for o in outcomes) == 19  # the reads that failed fast

    @pytest.mark.anyio
    async def test_cold_unknown_branch_is_not_remembered_and_keeps_its_error_type(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        mock_client.schema._fetch.side_effect = BranchNotFoundError(identifier="ghost")

        for _ in range(2):
            with pytest.raises(BranchNotFoundError):
                await get_cached_branch_schema(mock_ctx, branch="ghost")

        assert mock_client.schema._fetch.await_count == 2  # each read asked upstream; nothing was remembered
        assert "ghost" not in app_ctx.schema_cache_cold_failures


# ---------------------------------------------------------------------------
# A rejected credential is the caller's problem, not an upstream-health signal
# ---------------------------------------------------------------------------


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    """The exception ``raise_for_status()`` raises for *status_code* — how a 4xx/5xx from ``_get`` surfaces."""
    error: httpx.HTTPStatusError = _make_response(status_code=status_code).raise_for_status.side_effect
    return error


# The two shapes a rejected credential takes on this module's path: the SDK's
# ``_parse_schema_response`` and our ``_fetch_summary_hash`` both call
# ``raise_for_status()`` on a 401/403, and ``login()`` (username/password
# credentials) raises ``AuthenticationError`` when the token refresh is refused.
_AUTH_ERROR_FACTORIES = [
    pytest.param(lambda: _http_status_error(httpx.codes.UNAUTHORIZED), id="httpx-401"),
    pytest.param(lambda: _http_status_error(httpx.codes.FORBIDDEN), id="httpx-403"),
    pytest.param(lambda: AuthenticationError("token rejected"), id="sdk-AuthenticationError"),
]


class TestAuthErrorsAreCallerScoped:
    """A 401/403 says the *caller's* credential was rejected, not that Infrahub is unhealthy.

    In passthrough modes every request carries its own token. Before this,
    one caller's bad token armed the cold-failure marker against everyone
    (cold) or counted toward a breaker that fails everyone closed (warm), and
    that caller was handed the stale schema instead of the rejection.
    """

    @pytest.mark.anyio
    @pytest.mark.parametrize("make_error", _AUTH_ERROR_FACTORIES)
    async def test_cold_fetch_auth_error_reaches_the_caller_without_arming_the_cold_marker(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        caplog: pytest.LogCaptureFixture,
        make_error: Callable[[], Exception],
    ) -> None:
        mock_client.schema._fetch.side_effect = make_error()

        with caplog.at_level("WARNING", logger="infrahub_mcp.schema_cache"), pytest.raises(AuthenticationError):
            await get_cached_branch_schema(mock_ctx)

        assert "main" not in app_ctx.schema_cache
        assert "main" not in app_ctx.schema_cache_cold_failures
        assert any("schema_cache_auth_error" in r.message for r in caplog.records)
        assert not any("schema_cache_cold_fetch_failure" in r.message for r in caplog.records)

        # The next caller is not failed fast by the marker: it probes with its own credential.
        with pytest.raises(AuthenticationError):
            await get_cached_branch_schema(mock_ctx)
        assert mock_client.schema._fetch.await_count == 2

    @pytest.mark.anyio
    @pytest.mark.parametrize("make_error", _AUTH_ERROR_FACTORIES)
    async def test_probe_auth_error_reaches_the_caller_and_leaves_the_entry_untouched(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        mock_metrics: MagicMock,
        make_error: Callable[[], Exception],
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        entry = _past_window_entry(schema, now=schema_cache._now())
        app_ctx.schema_cache["main"] = entry
        mock_client._get.side_effect = make_error()

        with pytest.raises(AuthenticationError):
            await get_cached_branch_schema(mock_ctx)

        assert app_ctx.schema_cache["main"] is entry  # same object: counter, timestamps and SDL all untouched
        events = [c.args[0] for c in mock_metrics.record_schema_cache_event.call_args_list]
        assert "revalidate_failure" not in events
        assert "stale_hit" not in events
        mock_client.schema.set_cache.assert_not_called()  # the rejected caller is not handed the stale schema

        # No throttle armed: the next caller probes again with its own credential.
        with pytest.raises(AuthenticationError):
            await get_cached_branch_schema(mock_ctx)
        assert mock_client._get.await_count == 2

    @pytest.mark.anyio
    @pytest.mark.parametrize("status_code", [httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN])
    async def test_summary_response_with_an_auth_status_is_an_auth_error(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        clock: _FakeClock,
        status_code: int,
    ) -> None:
        """``_get`` returns the 401/403 response as-is; the error comes from our own ``raise_for_status()``."""
        schema = _make_branch_schema(schema_hash="H1")
        entry = _past_window_entry(schema, now=clock.now)
        app_ctx.schema_cache["main"] = entry
        mock_client._get.return_value = _make_response(status_code=status_code)

        with pytest.raises(AuthenticationError, match=f"HTTP {int(status_code)}"):
            await get_cached_branch_schema(mock_ctx)

        assert app_ctx.schema_cache["main"] is entry

    @pytest.mark.anyio
    @pytest.mark.parametrize("make_error", _AUTH_ERROR_FACTORIES)
    async def test_refetch_auth_error_after_a_hash_diff_leaves_the_entry_untouched(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        mock_metrics: MagicMock,
        make_error: Callable[[], Exception],
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        entry = _past_window_entry(schema, now=schema_cache._now())
        app_ctx.schema_cache["main"] = entry
        mock_client._get.return_value = _make_response(json_body={"main": "H2"})
        mock_client.schema._fetch.side_effect = make_error()

        with pytest.raises(AuthenticationError):
            await get_cached_branch_schema(mock_ctx)

        assert app_ctx.schema_cache["main"] is entry
        events = [c.args[0] for c in mock_metrics.record_schema_cache_event.call_args_list]
        assert "revalidate_failure" not in events
        assert "hash_diff" not in events
        mock_client.schema.set_cache.assert_not_called()

        # No throttle armed: the next caller probes again with its own credential.
        with pytest.raises(AuthenticationError):
            await get_cached_branch_schema(mock_ctx)
        assert mock_client.schema._fetch.await_count == 2

    @pytest.mark.anyio
    async def test_other_http_status_errors_remain_transient_on_the_warm_path(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        mock_metrics: MagicMock,
        clock: _FakeClock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = _past_window_entry(schema, now=clock.now)
        mock_client._get.return_value = _make_response(status_code=httpx.codes.INTERNAL_SERVER_ERROR)

        result = await get_cached_branch_schema(mock_ctx)

        assert result is schema  # served stale
        assert app_ctx.schema_cache["main"].consecutive_failures == 1
        assert app_ctx.schema_cache["main"].last_attempt_monotonic == clock.now
        mock_metrics.record_schema_cache_event.assert_any_call("revalidate_failure")

    @pytest.mark.anyio
    async def test_other_http_status_errors_still_arm_the_cold_marker(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        clock: _FakeClock,
    ) -> None:
        mock_client.schema._fetch.side_effect = _http_status_error(httpx.codes.INTERNAL_SERVER_ERROR)

        with pytest.raises(httpx.HTTPStatusError):
            await get_cached_branch_schema(mock_ctx)

        assert app_ctx.schema_cache_cold_failures["main"] == clock.now
        with pytest.raises(ToolError, match="Schema temporarily unavailable"):
            await get_cached_branch_schema(mock_ctx)  # inside the window: fail fast
        mock_client.schema._fetch.assert_awaited_once()


# ---------------------------------------------------------------------------
# Circuit break
# ---------------------------------------------------------------------------


class TestCircuitBreak:
    @pytest.mark.anyio
    async def test_broken_entry_fails_closed_when_recovery_probe_fails(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        # 10 consecutive failures already; the read retries upstream first and
        # only fails closed because that retry fails too.
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=schema_cache._now(),
            consecutive_failures=10,
        )
        mock_client._get.side_effect = httpx.NetworkError("still down")

        with pytest.raises(ToolError, match="circuit-break threshold"):
            await get_cached_branch_schema(mock_ctx)

        mock_client._get.assert_awaited()

    @pytest.mark.anyio
    async def test_broken_entry_recovers_when_upstream_returns(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        """A tripped breaker must not latch for the process lifetime."""
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=schema_cache._now() - 10_000,
            consecutive_failures=50,
        )
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})

        result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        entry = app_ctx.schema_cache["main"]
        assert entry.consecutive_failures == 0
        assert not schema_cache._is_circuit_broken(
            entry,
            max_consecutive_failures=app_ctx.config.schema_cache_max_consecutive_failures,
            max_staleness_seconds=app_ctx.config.schema_cache_max_staleness_seconds,
            now=schema_cache._now(),
        )

    @pytest.mark.anyio
    async def test_broken_entry_recovers_on_hash_diff(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        old_schema = _make_branch_schema(schema_hash="H1")
        new_schema = _make_branch_schema(schema_hash="H2")
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=old_schema,
            schema_hash="H1",
            graphql_sdl="old-sdl",
            fetched_at_monotonic=schema_cache._now() - 10_000,
            consecutive_failures=50,
        )
        mock_client._get.return_value = _make_response(json_body={"main": "H2"})
        mock_client.schema._fetch.return_value = new_schema
        mock_client.schema.get_graphql_schema.return_value = "new-sdl"

        result = await get_cached_branch_schema(mock_ctx)

        assert result is new_schema
        assert app_ctx.schema_cache["main"].consecutive_failures == 0
        assert app_ctx.schema_cache["main"].graphql_sdl == "new-sdl"

    @pytest.mark.anyio
    async def test_broken_entry_throttles_recovery_probes(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        """Reads during an outage fail fast instead of each paying a timeout."""
        schema = _make_branch_schema(schema_hash="H1")
        now = schema_cache._now()
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=now - 10_000,
            consecutive_failures=50,
            last_attempt_monotonic=now,  # probe just happened
        )

        with pytest.raises(ToolError, match="circuit-break threshold"):
            await get_cached_branch_schema(mock_ctx)

        mock_client._get.assert_not_awaited()
        mock_client.schema._fetch.assert_not_awaited()

    @pytest.mark.anyio
    async def test_recovery_probe_interval_is_clamped_below_a_large_ttl(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        """A long skip-window must not delay recovery by a whole TTL.

        With ``schema_cache_ttl`` at an hour, throttling recovery by the TTL
        would keep a tripped entry rejecting reads for an hour after Infrahub
        healed. The probe interval is clamped, so a probe one minute old is
        already due again.
        """
        app_ctx.config = _make_config(schema_cache_ttl=3600)
        now = schema_cache._now()
        healed = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=healed,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=now - 10_000,
            consecutive_failures=50,
            last_attempt_monotonic=now - 60,  # one minute since the last probe
        )
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})

        result = await get_cached_branch_schema(mock_ctx)

        assert result is healed
        mock_client._get.assert_awaited_once()
        assert app_ctx.schema_cache["main"].consecutive_failures == 0

    @pytest.mark.anyio
    async def test_recovery_probe_runs_once_per_window_under_burst(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        """A burst against a broken entry costs one upstream probe, not N."""
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=schema_cache._now() - 10_000,
            consecutive_failures=50,
        )
        mock_client._get.side_effect = httpx.NetworkError("still down")

        async def runner() -> Any:
            with pytest.raises(ToolError):
                await get_cached_branch_schema(mock_ctx)

        await asyncio.gather(*[asyncio.create_task(runner()) for _ in range(10)])

        assert mock_client._get.await_count == 1, (
            f"expected one recovery probe per window, got {mock_client._get.await_count}"
        )

    @pytest.mark.anyio
    async def test_threshold_zero_disables_circuit_break(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        app_ctx.config = _make_config(
            schema_cache_max_consecutive_failures=0,
            schema_cache_max_staleness_seconds=0,
        )
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=schema_cache._now() - 100_000,
            consecutive_failures=999,
        )
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})

        result = await get_cached_branch_schema(mock_ctx)

        # Both thresholds disabled — serve stale even after extreme failure count and age.
        assert result is schema

    @pytest.mark.anyio
    async def test_successful_revalidation_resets_failure_counter(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        old_time = schema_cache._now() - 100  # past skip-window, under staleness ceiling
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=old_time,
            consecutive_failures=5,
        )
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})

        await get_cached_branch_schema(mock_ctx)

        assert app_ctx.schema_cache["main"].consecutive_failures == 0

    @pytest.mark.anyio
    async def test_circuit_break_metric_counts_transitions_not_blocked_reads(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        mock_metrics: MagicMock,
    ) -> None:
        # ttl=0 disables both the skip-window and the retry throttle, so every
        # read below really does attempt revalidation.
        app_ctx.config = _make_config(schema_cache_ttl=0, schema_cache_max_consecutive_failures=2)
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=_make_branch_schema(schema_hash="H1"),
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=schema_cache._now(),
            consecutive_failures=1,
        )
        mock_client._get.side_effect = httpx.NetworkError("down")

        for _ in range(3):
            with pytest.raises(ToolError):
                await get_cached_branch_schema(mock_ctx)

        breaks = [c for c in mock_metrics.record_schema_cache_event.call_args_list if c.args[0] == "circuit_break"]
        assert len(breaks) == 1, f"expected one transition, got {len(breaks)} (counting blocked reads)"

    @pytest.mark.anyio
    async def test_staleness_trip_is_recorded_on_the_first_failed_probe(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        mock_metrics: MagicMock,
    ) -> None:
        """A staleness trip has no read to observe the threshold elapsing.

        The entry is already past ``max_staleness`` before anyone reads it, so
        comparing broken-before to broken-after would see no transition and
        never count the trip.
        """
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=_make_branch_schema(schema_hash="H1"),
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=schema_cache._now() - 10_000,  # already past max_staleness
            consecutive_failures=0,
        )
        mock_client._get.side_effect = httpx.NetworkError("down")

        with pytest.raises(ToolError, match="circuit-break threshold"):
            await get_cached_branch_schema(mock_ctx)

        breaks = [c for c in mock_metrics.record_schema_cache_event.call_args_list if c.args[0] == "circuit_break"]
        assert len(breaks) == 1
        assert app_ctx.schema_cache["main"].circuit_break_recorded is True

    @pytest.mark.anyio
    async def test_recovery_clears_the_recorded_break_so_a_later_trip_counts(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=_make_branch_schema(schema_hash="H1"),
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=schema_cache._now() - 10_000,
            consecutive_failures=50,
            circuit_break_recorded=True,
        )
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})

        await get_cached_branch_schema(mock_ctx)

        assert app_ctx.schema_cache["main"].circuit_break_recorded is False

    @pytest.mark.anyio
    async def test_circuit_break_without_metrics_middleware_raises_tool_error(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A break with metrics unconfigured must surface ToolError, not AttributeError."""
        monkeypatch.setattr(schema_cache, "_get_metrics", lambda: None)
        app_ctx.config = _make_config(schema_cache_max_consecutive_failures=1)
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=_make_branch_schema(schema_hash="H1"),
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=schema_cache._now() - 100,  # past skip-window
            consecutive_failures=0,
        )
        mock_client._get.side_effect = httpx.NetworkError("down")

        with pytest.raises(ToolError, match="circuit-break threshold"):
            await get_cached_branch_schema(mock_ctx)


# ---------------------------------------------------------------------------
# US4 — Metrics
# ---------------------------------------------------------------------------


class TestMetrics:
    @pytest.mark.anyio
    async def test_metrics_counters_increment_across_paths(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        mock_metrics: MagicMock,
    ) -> None:
        # Cold fetch.
        schema = _make_branch_schema(schema_hash="H1")
        mock_client.schema._fetch.return_value = schema
        await get_cached_branch_schema(mock_ctx)

        # Warm hit.
        await get_cached_branch_schema(mock_ctx)

        # Past TTL hash match: time-warp the entry's fetched_at backward.
        old_entry = app_ctx.schema_cache["main"]
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch=old_entry.branch,
            schema=old_entry.schema,
            schema_hash=old_entry.schema_hash,
            graphql_sdl=old_entry.graphql_sdl,
            fetched_at_monotonic=schema_cache._now() - 100,
            consecutive_failures=0,
        )
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})
        await get_cached_branch_schema(mock_ctx)

        events = [c.args[0] for c in mock_metrics.record_schema_cache_event.call_args_list]
        assert "miss" in events
        assert "hit" in events
        assert "hash_match" in events


class TestMetricsMiddlewareSchemaCacheCounters:
    def test_record_schema_cache_event_increments(self) -> None:
        mw = MetricsMiddleware()
        for _ in range(3):
            mw.record_schema_cache_event("hit")
        mw.record_schema_cache_event("miss")
        mw.record_schema_cache_event("unknown")  # ignored

        snap = mw.snapshot()
        assert snap["schema_cache"]["hit"] == 3
        assert snap["schema_cache"]["miss"] == 1
        # Unknown events are silently ignored.
        assert "unknown" not in snap["schema_cache"]

    def test_stale_hit_is_a_declared_counter(self) -> None:
        """Stale serves during an outage must be visible, not folded into ``hit`` or dropped as unknown."""
        mw = MetricsMiddleware()
        mw.record_schema_cache_event("stale_hit")

        assert mw.snapshot()["schema_cache"]["stale_hit"] == 1
        assert "infrahub_mcp_schema_cache_stale_hit_total 1" in mw.prometheus_text()

    def test_prometheus_text_includes_schema_cache_counters(self) -> None:
        mw = MetricsMiddleware()
        mw.record_schema_cache_event("hit")
        mw.record_schema_cache_event("hash_diff")

        text = mw.prometheus_text()
        assert "infrahub_mcp_schema_cache_hit_total 1" in text
        assert "infrahub_mcp_schema_cache_hash_diff_total 1" in text
        assert "# TYPE infrahub_mcp_schema_cache_hit_total counter" in text


# ---------------------------------------------------------------------------
# GraphQL SDL
# ---------------------------------------------------------------------------


class TestGraphQLSDL:
    @pytest.mark.anyio
    async def test_cold_fetch_includes_sdl(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        mock_client.schema._fetch.return_value = schema
        mock_client.schema.get_graphql_schema.return_value = "schema { Query }"

        sdl = await get_cached_graphql_sdl(mock_ctx)

        assert sdl == "schema { Query }"
        assert app_ctx.schema_cache["main"].graphql_sdl == "schema { Query }"

    @pytest.mark.anyio
    async def test_sdl_invalidates_with_schema_hash(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        old_schema = _make_branch_schema(schema_hash="H1")
        new_schema = _make_branch_schema(schema_hash="H2")
        old_time = schema_cache._now() - 100  # past skip-window, under staleness ceiling
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=old_schema,
            schema_hash="H1",
            graphql_sdl="old-sdl",
            fetched_at_monotonic=old_time,
            consecutive_failures=0,
        )
        mock_client._get.return_value = _make_response(json_body={"main": "H2"})
        mock_client.schema.get_graphql_schema.return_value = "new-sdl"
        mock_client.schema._fetch.return_value = new_schema

        sdl = await get_cached_graphql_sdl(mock_ctx)

        assert sdl == "new-sdl"

    @pytest.mark.anyio
    async def test_sdl_is_fetched_for_the_requested_branch(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        """The SDL must be pinned to the same branch as the structured schema."""
        schema = _make_branch_schema(schema_hash="H1")
        mock_client.schema._fetch.return_value = schema
        mock_client.schema.get_graphql_schema.return_value = "branch-sdl"

        sdl = await get_cached_graphql_sdl(mock_ctx, branch="feature-x")

        assert sdl == "branch-sdl"
        mock_client.schema.get_graphql_schema.assert_awaited_once_with(branch="feature-x")
        assert app_ctx.schema_cache["feature-x"].graphql_sdl == "branch-sdl"

    @pytest.mark.anyio
    async def test_disabled_cache_still_fetches_sdl_for_the_requested_branch(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        app_ctx.config = _make_config(schema_cache_enabled=False)
        mock_client.schema.get_graphql_schema.return_value = "branch-sdl"

        sdl = await get_cached_graphql_sdl(mock_ctx, branch="feature-x")

        assert sdl == "branch-sdl"
        mock_client.schema.get_graphql_schema.assert_awaited_once_with(branch="feature-x")

    @pytest.mark.anyio
    async def test_sdl_failure_on_cold_fetch_still_serves_the_structured_schema(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An outage of ``/schema.graphql`` alone must not take down get_schema, get_nodes or the write tools."""
        schema = _make_branch_schema(schema_hash="H1", kinds=["InfraDevice"])
        mock_client.schema._fetch.return_value = schema
        mock_client.schema.get_graphql_schema.side_effect = ValueError("schema.graphql: 502")

        with caplog.at_level("WARNING", logger="infrahub_mcp.schema_cache"):
            result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        entry = app_ctx.schema_cache["main"]
        assert entry.schema is schema
        assert entry.graphql_sdl is None
        assert entry.consecutive_failures == 0
        mock_client.schema.set_cache.assert_called_once_with(schema=schema, branch="main")
        assert sum("schema_cache_sdl_fetch_failure" in r.message for r in caplog.records) == 1
        assert not any("schema_cache_cold_fetch_failure" in r.message for r in caplog.records)

    @pytest.mark.anyio
    async def test_sdl_only_failure_does_not_arm_the_cold_failure_throttle(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        mock_client.schema._fetch.return_value = schema
        mock_client.schema.get_graphql_schema.side_effect = ValueError("down")

        first = await get_cached_branch_schema(mock_ctx)
        second = await get_cached_branch_schema(mock_ctx)  # inside the window: must be a hit, not a fail-fast

        assert first is schema
        assert second is schema
        assert "main" not in app_ctx.schema_cache_cold_failures
        mock_client.schema._fetch.assert_awaited_once()

    @pytest.mark.anyio
    async def test_missing_sdl_is_filled_lazily_with_one_fetch(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        mock_client.schema._fetch.return_value = schema
        mock_client.schema.get_graphql_schema.side_effect = ValueError("down")
        await get_cached_branch_schema(mock_ctx)
        assert app_ctx.schema_cache["main"].graphql_sdl is None

        # The SDL endpoint recovers: the first SDL read fills the entry, the second is a pure hit.
        mock_client.schema.get_graphql_schema.side_effect = None
        mock_client.schema.get_graphql_schema.return_value = "schema { Query }"

        first = await get_cached_graphql_sdl(mock_ctx)
        second = await get_cached_graphql_sdl(mock_ctx)

        assert first == second == "schema { Query }"
        assert app_ctx.schema_cache["main"].graphql_sdl == "schema { Query }"
        assert app_ctx.schema_cache["main"].schema is schema  # the fill amended the entry, it did not replace it
        assert mock_client.schema.get_graphql_schema.await_count == 2  # one failed cold attempt + one lazy fill
        mock_client.schema._fetch.assert_awaited_once()

    @pytest.mark.anyio
    async def test_failed_lazy_fill_fails_the_sdl_read_alone(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        entry = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl=None,
            fetched_at_monotonic=schema_cache._now(),
        )
        app_ctx.schema_cache["main"] = entry
        mock_client.schema.get_graphql_schema.side_effect = ValueError("still down")

        with pytest.raises(ValueError, match="still down"):
            await get_cached_graphql_sdl(mock_ctx)

        stamped = app_ctx.schema_cache["main"]
        assert stamped.schema is schema  # amended in place, nothing evicted
        assert stamped.consecutive_failures == 0  # no failure counted toward the breaker
        assert stamped.graphql_sdl is None
        assert stamped.graphql_sdl_last_failure_monotonic is not None  # only the SDL fill throttle is armed
        assert await get_cached_branch_schema(mock_ctx) is schema
        mock_client.schema._fetch.assert_not_awaited()

    @pytest.mark.anyio
    async def test_hash_diff_refetch_with_failing_sdl_keeps_the_new_structured_schema(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        mock_metrics: MagicMock,
    ) -> None:
        old_schema = _make_branch_schema(schema_hash="H1")
        new_schema = _make_branch_schema(schema_hash="H2", kinds=["NewKind"])
        app_ctx.schema_cache["main"] = _past_window_entry(old_schema, now=schema_cache._now())
        mock_client._get.return_value = _make_response(json_body={"main": "H2"})
        mock_client.schema._fetch.return_value = new_schema
        mock_client.schema.get_graphql_schema.side_effect = ValueError("down")

        result = await get_cached_branch_schema(mock_ctx)

        assert result is new_schema
        entry = app_ctx.schema_cache["main"]
        assert entry.schema_hash == "H2"
        assert entry.graphql_sdl is None
        assert entry.consecutive_failures == 0
        recorded = [c.args[0] for c in mock_metrics.record_schema_cache_event.call_args_list]
        assert "hash_diff" in recorded
        assert "revalidate_failure" not in recorded

    @pytest.mark.anyio
    async def test_concurrent_sdl_reads_behind_a_missing_sdl_cost_one_fetch(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl=None,
            fetched_at_monotonic=schema_cache._now(),
        )
        release = asyncio.Event()

        async def slow_sdl(branch: str) -> str:
            await release.wait()
            return f"sdl-{branch}"

        mock_client.schema.get_graphql_schema.side_effect = slow_sdl

        tasks = [asyncio.create_task(get_cached_graphql_sdl(mock_ctx)) for _ in range(10)]
        await asyncio.sleep(0)  # park every reader on the cache lock behind the first fill
        release.set()
        results = await asyncio.gather(*tasks)

        assert results == ["sdl-main"] * 10
        assert mock_client.schema.get_graphql_schema.await_count == 1

    @pytest.mark.anyio
    async def test_failed_lazy_fill_throttles_further_sdl_reads(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        clock: _FakeClock,
    ) -> None:
        """During an SDL outage the resource costs one upstream timeout per window, not one per read."""
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl=None,
            fetched_at_monotonic=clock.now,
        )
        mock_client.schema.get_graphql_schema.side_effect = ValueError("still down")

        with pytest.raises(ValueError, match="still down"):
            await get_cached_graphql_sdl(mock_ctx)
        assert app_ctx.schema_cache["main"].graphql_sdl_last_failure_monotonic == clock.now

        clock.advance(5)
        with pytest.raises(ToolError, match=r"GraphQL SDL fetch failed 5 s ago.*next upstream attempt is in 25 s"):
            await get_cached_graphql_sdl(mock_ctx)

        mock_client.schema.get_graphql_schema.assert_awaited_once()  # the second read never went upstream

    @pytest.mark.anyio
    async def test_sdl_fill_is_retried_once_the_window_has_elapsed(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        clock: _FakeClock,
    ) -> None:
        """The window is ``min(ttl, 30)``: with a 60 s skip-window the fill retries after 30 s, and a success sticks."""
        app_ctx.config = _make_config(schema_cache_ttl=60)
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl=None,
            fetched_at_monotonic=clock.now,
        )
        mock_client.schema.get_graphql_schema.side_effect = ValueError("down")
        with pytest.raises(ValueError, match="down"):
            await get_cached_graphql_sdl(mock_ctx)

        clock.advance(31)  # past the 30 s throttle, still inside the 60 s skip-window
        mock_client.schema.get_graphql_schema.side_effect = None
        mock_client.schema.get_graphql_schema.return_value = "schema { Query }"

        first = await get_cached_graphql_sdl(mock_ctx)
        second = await get_cached_graphql_sdl(mock_ctx)

        assert first == second == "schema { Query }"
        assert app_ctx.schema_cache["main"].graphql_sdl == "schema { Query }"
        assert mock_client.schema.get_graphql_schema.await_count == 2  # one failed fill + one successful fill
        mock_client._get.assert_not_awaited()  # the structured schema never left the skip-window

    @pytest.mark.anyio
    async def test_ttl_zero_disables_the_sdl_fill_throttle(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        clock: _FakeClock,
    ) -> None:
        app_ctx.config = _make_config(schema_cache_ttl=0)
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl=None,
            fetched_at_monotonic=clock.now,
        )
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})  # ttl=0: every read probes
        mock_client.schema.get_graphql_schema.side_effect = ValueError("down")

        for _ in range(3):
            with pytest.raises(ValueError, match="down"):
                await get_cached_graphql_sdl(mock_ctx)

        assert mock_client.schema.get_graphql_schema.await_count == 3

    @pytest.mark.anyio
    async def test_sdl_fill_throttle_leaves_structured_reads_alone(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        clock: _FakeClock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl=None,
            fetched_at_monotonic=clock.now,
        )
        mock_client.schema.get_graphql_schema.side_effect = ValueError("down")
        with pytest.raises(ValueError, match="down"):
            await get_cached_graphql_sdl(mock_ctx)

        clock.advance(5)
        result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        entry = app_ctx.schema_cache["main"]
        assert entry.consecutive_failures == 0
        assert entry.graphql_sdl_last_failure_monotonic == clock.now - 5
        mock_client._get.assert_not_awaited()  # inside the skip-window: the SDL stamp forces no probe
        mock_client.schema._fetch.assert_not_awaited()


# ---------------------------------------------------------------------------
# Middleware schema-URI bypass
# ---------------------------------------------------------------------------


class TestSchemaAwareCachingMiddleware:
    @pytest.mark.anyio
    async def test_schema_uri_bypasses_cache(self) -> None:
        mw = _SchemaAwareResponseCachingMiddleware(
            list_tools_settings=ListToolsSettings(ttl=300),
            list_resources_settings=ListResourcesSettings(ttl=300),
            list_prompts_settings=ListPromptsSettings(ttl=300),
            read_resource_settings=ReadResourceSettings(ttl=300),
            call_tool_settings=CallToolSettings(ttl=300),
        )

        mock_msg = MagicMock()
        mock_msg.uri = "infrahub://schema"
        mock_ctx = MagicMock()
        mock_ctx.message = mock_msg

        call_next_count = 0

        async def call_next(context: Any) -> str:  # noqa: RUF029  # FastMCP middleware contract requires async
            del context
            nonlocal call_next_count
            call_next_count += 1
            return "fresh-response"

        # Two calls should both bypass the cache and hit call_next.
        result_1 = await mw.on_read_resource(mock_ctx, call_next)
        result_2 = await mw.on_read_resource(mock_ctx, call_next)
        assert result_1 == "fresh-response"
        assert result_2 == "fresh-response"
        assert call_next_count == 2, "schema URI must not be cached"

    @pytest.mark.anyio
    async def test_non_schema_uri_uses_parent_cache(self) -> None:
        mw = _SchemaAwareResponseCachingMiddleware(
            list_tools_settings=ListToolsSettings(ttl=300),
            list_resources_settings=ListResourcesSettings(ttl=300),
            list_prompts_settings=ListPromptsSettings(ttl=300),
            read_resource_settings=ReadResourceSettings(ttl=300),
            call_tool_settings=CallToolSettings(ttl=300),
        )

        mock_msg = MagicMock()
        mock_msg.uri = "infrahub://branches"
        mock_ctx = MagicMock()
        mock_ctx.message = mock_msg

        # The parent ResponseCachingMiddleware.on_read_resource should be invoked.
        # We can't easily assert "cache hit" without touching FastMCP internals,
        # but we can assert the bypass branch is NOT taken (call_next called
        # exactly once on first call, then cached).
        with patch(
            "fastmcp.server.middleware.caching.ResponseCachingMiddleware.on_read_resource",
            new_callable=AsyncMock,
        ) as parent:
            parent.return_value = "via-parent"
            result = await mw.on_read_resource(mock_ctx, AsyncMock(return_value="raw"))

        assert result == "via-parent"
        parent.assert_awaited_once()

    @pytest.mark.anyio
    async def test_tool_calls_are_never_cached(self) -> None:
        """No tool result may be replayed at the TTL layer.

        ``get_schema`` is owned by the schema cache; every other tool either
        returns live data or mutates state. Regression guard for an
        ``excluded_tools=["get_schema"]`` setting, which FastMCP reads as
        "cache everything except get_schema".
        """
        mw = _SchemaAwareResponseCachingMiddleware(
            list_tools_settings=ListToolsSettings(ttl=300),
            list_resources_settings=ListResourcesSettings(ttl=300),
            list_prompts_settings=ListPromptsSettings(ttl=300),
            read_resource_settings=ReadResourceSettings(ttl=300),
            call_tool_settings=CallToolSettings(ttl=300),
        )

        calls = 0

        async def call_next(context: Any) -> str:  # noqa: RUF029  # FastMCP middleware contract requires async
            del context
            nonlocal calls
            calls += 1
            return f"result-{calls}"

        for tool_name in ("get_schema", "get_nodes", "node_upsert", "mutate_graphql"):
            mock_msg = MagicMock()
            mock_msg.name = tool_name
            mock_msg.arguments = {"same": "args"}
            mock_ctx = MagicMock()
            mock_ctx.message = mock_msg

            first = await mw.on_call_tool(mock_ctx, call_next)
            second = await mw.on_call_tool(mock_ctx, call_next)
            assert first != second, f"{tool_name} result was replayed from cache"

        assert calls == 8, f"expected every call to reach the tool, got {calls}"


class TestResponseCachingMiddlewareBuilder:
    def test_schema_cache_enabled_leaves_no_tool_allowlist(self) -> None:
        """An empty allowlist must be expressed by the bypass, not by settings.

        FastMCP's ``_matches_tool_cache_settings`` reads both filters with a
        truthiness check, so ``included_tools=[]`` means "no filter" and
        ``excluded_tools=["get_schema"]`` means "cache every other tool".
        """
        mw = _build_response_caching_middleware(_make_config(schema_cache_enabled=True, cache_enabled=True))

        assert isinstance(mw, _SchemaAwareResponseCachingMiddleware)
        assert not mw._call_tool_settings.get("included_tools")
        assert not mw._call_tool_settings.get("excluded_tools")
        assert mw._matches_tool_cache_settings("node_upsert") is True, (
            "settings alone do not block tool caching — on_call_tool must"
        )

    def test_schema_cache_disabled_keeps_get_schema_allowlist(self) -> None:
        mw = _build_response_caching_middleware(_make_config(schema_cache_enabled=False, cache_enabled=True))

        assert not isinstance(mw, _SchemaAwareResponseCachingMiddleware)
        assert mw._call_tool_settings.get("included_tools") == ["get_schema"]
        assert mw._matches_tool_cache_settings("get_schema") is True
        assert mw._matches_tool_cache_settings("node_upsert") is False


# ---------------------------------------------------------------------------
# Catalog coverage
# ---------------------------------------------------------------------------


class TestCatalogIncludesGenerics:
    @pytest.mark.anyio
    async def test_generic_kinds_are_discoverable(
        self,
        mock_ctx: MagicMock,
        mock_client: MagicMock,
    ) -> None:
        """Generics reach the catalog because the SDK folds them into ``nodes``.

        ``BranchSchema.from_api_response`` merges the API's ``nodes``,
        ``generics``, ``profiles`` and ``templates`` lists into one ``nodes``
        mapping, which is exactly what ``client.schema.all()`` returns. Reading
        ``branch_schema.nodes`` is therefore not a node-only view, and generic
        kinds such as ``CoreNode`` stay reachable through ``get_schema`` and the
        schema resource. Guard against "fixing" this by reaching for a separate
        ``generics`` attribute that does not exist.
        """
        schema = _make_branch_schema(schema_hash="H1")
        for kind, namespace in (("InfraDevice", "Infra"), ("CoreNode", "Core")):
            node = MagicMock()
            node.kind = kind
            node.namespace = namespace
            node.label = kind
            schema.nodes[kind] = node
        mock_client.schema._fetch.return_value = schema

        catalog = await get_schema_catalog(mock_ctx)

        assert "CoreNode" in catalog
        assert "InfraDevice" in catalog
        kind_obj = await get_cached_kind(mock_ctx, kind="CoreNode")
        assert kind_obj is schema.nodes["CoreNode"]
