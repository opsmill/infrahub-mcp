"""Tests for the hash-validated schema cache (``schema_cache.py``).

This file mocks the SDK's ``InfrahubClient._get`` private method extensively
because the schema-cache module deliberately calls it to reach the
``GET /api/schema/summary`` endpoint that the SDK does not yet wrap publicly,
and ``GET /schema.graphql``, whose SDK wrapper neither encodes the branch nor
types a non-200. The file-level ``ruff: noqa: SLF001`` is therefore intentional.
"""

# ruff: noqa: SLF001

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, NoReturn
from unittest.mock import DEFAULT, AsyncMock, MagicMock, patch
from urllib.parse import urlencode

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
from infrahub_mcp import utils as mcp_utils
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


_SUMMARY_PATH = "/api/schema/summary"
_SDL_PATH = "/schema.graphql"


def _sdl_url(client: MagicMock, branch: str) -> str:
    """The URL ``_fetch_graphql_sdl`` is expected to ask for *branch*'s SDL at."""
    return f"{client.address}{_SDL_PATH}?{urlencode([('branch', branch)])}"


def _route_get(client: MagicMock) -> Callable[..., Awaitable[Any]]:
    """``client._get`` side effect routing ``/schema.graphql`` to ``client.sdl_get``.

    Both endpoints go through ``client._get``, but the tests configure them
    independently: ``_get.return_value`` / ``_get.side_effect`` keep describing
    the summary probe, as they always did, and :func:`_set_sdl` /
    :func:`_fail_sdl` describe the SDL. Returning ``DEFAULT`` hands a
    non-SDL URL back to the mock's own ``return_value``.
    """

    async def route(url: str, **_: Any) -> Any:
        if _SDL_PATH in url:
            return await client.sdl_get(url=url)
        return DEFAULT

    return route


def _set_sdl(client: MagicMock, text: str) -> None:
    """Make ``GET /schema.graphql`` answer 200 with *text*."""
    client.sdl_get.side_effect = None
    client.sdl_get.return_value = _make_response(text=text)


def _fail_sdl(client: MagicMock, failure: int | BaseException) -> None:
    """Make ``GET /schema.graphql`` answer HTTP status *failure*, or make ``client._get`` raise it.

    An ``int`` models the endpoint answering a non-200 (``raise_for_status()``
    turns it into ``httpx.HTTPStatusError``); an exception models a failure
    before any answer — a network error, or ``login()`` refusing the caller.
    """
    if isinstance(failure, int):
        client.sdl_get.side_effect = None
        client.sdl_get.return_value = _make_response(status_code=failure)
    else:
        client.sdl_get.side_effect = failure


def _summary_probes(client: MagicMock) -> int:
    """How many times ``client._get`` was awaited for ``/api/schema/summary``."""
    return sum(_SUMMARY_PATH in call.kwargs["url"] for call in client._get.await_args_list)


def _make_client() -> MagicMock:
    """Build an ``InfrahubClient`` mock whose SDK schema cache behaves like the real one.

    ``schema.cache`` is a real dict and ``schema.set_cache`` writes into it, so
    the ``schema_cache_enabled=False`` path — which reads that cache before
    fetching — sees the same hit/miss behaviour the SDK provides. ``_get``
    routes ``/schema.graphql`` to ``sdl_get`` (see :func:`_route_get`), which
    answers ``"sdl"`` until a test says otherwise.
    """
    client = MagicMock()
    client.address = "http://infrahub.test"
    client.schema = MagicMock()
    client.schema.cache = {}
    client.schema._fetch = AsyncMock()
    client.schema.set_cache = MagicMock(
        side_effect=lambda schema, branch: client.schema.cache.__setitem__(branch, schema)
    )
    client.sdl_get = AsyncMock(return_value=_make_response(text="sdl"))
    client._get = AsyncMock(side_effect=_route_get(client))
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
    """Patch ``utils.get_client`` (the seam ``resolve_client`` uses) and get_default_branch for the module."""
    monkeypatch.setattr(mcp_utils, "get_client", lambda _ctx: mock_client)

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
        _set_sdl(mock_client, "schema { Query }")

        result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        assert "main" in app_ctx.schema_cache
        assert app_ctx.schema_cache["main"].schema_hash == "H1"
        assert _summary_probes(mock_client) == 0  # the hash came with /api/schema: no /summary fallback
        mock_client.schema._fetch.assert_awaited_once_with(branch="main")
        mock_client.schema.set_cache.assert_called_once_with(schema=schema, branch="main")
        mock_metrics.record_schema_cache_event.assert_any_call("miss")

    @pytest.mark.anyio
    async def test_cold_fetch_without_a_hash_stores_an_empty_hash_and_repairs_it_on_the_first_probe(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        mock_metrics: MagicMock,
        clock: _FakeClock,
    ) -> None:
        """``/api/schema`` omitted ``main``: the cold entry stores ``""`` and makes no ``/summary`` call.

        A hash probed *after* the fetch could pair a newer hash with older
        content and hide that change from every later probe. Instead the
        empty hash mismatches the first probe past the skip-window and the
        refetch stores the probe's (pre-fetch) hash: one extra refetch, after
        which the entry hash-matches like any other.
        """
        schema = _make_branch_schema(schema_hash="")  # the SDK's default when /api/schema omits ``main``
        mock_client.schema._fetch.return_value = schema
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})

        result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        assert not app_ctx.schema_cache["main"].schema_hash  # stored as "" on purpose
        assert _summary_probes(mock_client) == 0  # no /summary probe during the cold fetch
        mock_client.schema._fetch.assert_awaited_once_with(branch="main")
        mock_metrics.record_schema_cache_event.assert_any_call("miss")

        # Past the skip-window: the probe reports H1, "" mismatches, one full refetch stores H1.
        clock.advance(31)
        mock_metrics.record_schema_cache_event.reset_mock()

        again = await get_cached_branch_schema(mock_ctx)

        assert again is schema
        assert _summary_probes(mock_client) == 1
        assert mock_client.schema._fetch.await_count == 2
        assert app_ctx.schema_cache["main"].schema_hash == "H1"  # the probe hash, taken before the refetch
        mock_metrics.record_schema_cache_event.assert_any_call("hash_diff")

        # Past the skip-window again: the entry hash-matches and nothing is refetched.
        clock.advance(31)
        mock_metrics.record_schema_cache_event.reset_mock()

        third = await get_cached_branch_schema(mock_ctx)

        assert third is schema
        assert _summary_probes(mock_client) == 2
        assert mock_client.schema._fetch.await_count == 2
        assert app_ctx.schema_cache["main"].schema_hash == "H1"
        events = [c.args[0] for c in mock_metrics.record_schema_cache_event.call_args_list]
        assert "hash_match" in events
        assert "hash_diff" not in events

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
        monkeypatch.setattr(mcp_utils, "get_client", lambda _ctx: next(remaining))

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


def _patch_fresh_client_per_call(
    monkeypatch: pytest.MonkeyPatch,
    *,
    configure: Callable[[MagicMock], None] | None = None,
) -> list[MagicMock]:
    """Make ``get_client`` build a distinct client on every call and record each one.

    That is the passthrough-mode shape. The module fixture hands every call the
    same ``mock_client``, which cannot tell a read that primed the caller's
    client from one that primed a throwaway of its own.
    """
    built: list[MagicMock] = []

    def build(_ctx: Any) -> MagicMock:
        client = _make_client()
        if configure is not None:
            configure(client)
        built.append(client)
        return client

    monkeypatch.setattr(mcp_utils, "get_client", build)
    return built


class TestPrimedClientIsTheCallers:
    """The SDK cache a read primes must belong to the client the caller keeps using.

    In the passthrough auth modes a client the helper resolved for itself is
    primed and dropped on return, while the tool's own client refetches
    ``/api/schema`` on its first ``client.filters``. A read handed a client
    must therefore prime that one and resolve none; a read without one must
    resolve exactly one and run every upstream call through it.
    """

    @pytest.mark.anyio
    async def test_cold_kind_read_primes_the_callers_client_and_resolves_none(
        self,
        mock_ctx: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        built = _patch_fresh_client_per_call(monkeypatch)
        schema = _make_branch_schema(schema_hash="H1", kinds=["InfraDevice"])
        caller = _make_client()
        caller.schema._fetch.return_value = schema

        kind = await get_cached_kind(mock_ctx, kind="InfraDevice", client=caller)

        assert kind is schema.nodes["InfraDevice"]
        caller.schema._fetch.assert_awaited_once_with(branch="main")
        assert caller.schema.cache["main"] is schema
        assert built == []

    @pytest.mark.anyio
    async def test_warm_branch_schema_read_primes_the_callers_client_and_resolves_none(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        built = _patch_fresh_client_per_call(monkeypatch)
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=schema_cache._now(),
            consecutive_failures=0,
        )
        caller = _make_client()

        result = await get_cached_branch_schema(mock_ctx, client=caller)

        assert result is schema
        assert caller.schema.cache["main"] is schema
        caller.schema._fetch.assert_not_awaited()
        assert built == []

    @pytest.mark.anyio
    async def test_forced_revalidation_on_kind_miss_runs_through_the_callers_client(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The ``tools/nodes.py`` peer loop: a miss must probe and refetch on the tool's own client."""
        built = _patch_fresh_client_per_call(monkeypatch)
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
        caller = _make_client()
        caller._get.return_value = _make_response(json_body={"main": "H2"})
        caller.schema._fetch.return_value = new_schema

        kind = await get_cached_kind(mock_ctx, kind="NewKind", client=caller)

        assert kind is new_schema.nodes["NewKind"]
        assert _summary_probes(caller) == 1
        caller.schema._fetch.assert_awaited_once()
        assert caller.schema.cache["main"] is new_schema
        assert built == []

    @pytest.mark.anyio
    async def test_sdl_read_without_client_resolves_one_client_for_probe_and_lazy_fill(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``infrahub://graphql-schema`` omits the client: the probe and the SDL fill share the one resolved."""

        def configure(client: MagicMock) -> None:
            client._get.return_value = _make_response(json_body={"main": "H1"})
            _set_sdl(client, "filled-sdl")

        built = _patch_fresh_client_per_call(monkeypatch, configure=configure)
        schema = _make_branch_schema(schema_hash="H1")
        old_time = schema_cache._now() - 100  # past skip-window
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl=None,  # a lazy fill is due
            fetched_at_monotonic=old_time,
            consecutive_failures=0,
        )

        sdl = await get_cached_graphql_sdl(mock_ctx)

        assert sdl == "filled-sdl"
        assert len(built) == 1
        (client,) = built
        assert _summary_probes(client) == 1
        client.schema._fetch.assert_not_awaited()
        client.sdl_get.assert_awaited_once_with(url=_sdl_url(client, "main"))
        assert client.schema.cache["main"] is schema
        assert app_ctx.schema_cache["main"].graphql_sdl == "filled-sdl"

    @pytest.mark.anyio
    async def test_kind_read_without_client_resolves_one_client_for_read_and_forced_revalidation(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``schema.py`` omits the client: the first read and the miss-driven probe share the one resolved."""

        def configure(client: MagicMock) -> None:
            client._get.return_value = _make_response(json_body={"main": "H2"})
            client.schema._fetch.return_value = new_schema
            _set_sdl(client, "new-sdl")

        old_schema = _make_branch_schema(schema_hash="H1", kinds=["InfraDevice"])
        new_schema = _make_branch_schema(schema_hash="H2", kinds=["InfraDevice", "NewKind"])
        built = _patch_fresh_client_per_call(monkeypatch, configure=configure)
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=old_schema,
            schema_hash="H1",
            graphql_sdl="old-sdl",
            fetched_at_monotonic=schema_cache._now(),
            consecutive_failures=0,
        )

        kind = await get_cached_kind(mock_ctx, kind="NewKind")

        assert kind is new_schema.nodes["NewKind"]
        assert len(built) == 1
        (client,) = built
        assert _summary_probes(client) == 1
        client.schema._fetch.assert_awaited_once()
        assert client.schema.cache["main"] is new_schema


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


class TestPerBranchLock:
    """The cache lock is per branch: one branch's upstream call never queues another branch's reads.

    The lock is held across the upstream call — up to its timeout. With one
    lock for the whole cache, a cold fetch or probe for branch ``a`` held
    every other branch's lock-path reads, healthy ones included, behind it;
    during an outage with N branches in play, reads serialized behind N
    upstream timeouts. Single-flight *within* a branch is unchanged
    (:class:`TestSingleFlight`), and the lazy SDL fill for a branch takes
    the same lock as its structured read.

    A lock lives only as long as it is of use: kept while anyone holds or
    waits on it, or the branch has a cache entry, and dropped once the last
    reader leaves a branch with no entry — branch names are caller input, so
    a lock per name ever asked for grew without bound.
    """

    @pytest.mark.anyio
    async def test_a_parked_cold_fetch_for_one_branch_does_not_block_another(
        self,
        mock_ctx: MagicMock,
        mock_client: MagicMock,
    ) -> None:
        schema_a = _make_branch_schema(schema_hash="HA")
        schema_b = _make_branch_schema(schema_hash="HB")
        entered_a = asyncio.Event()
        release_a = asyncio.Event()

        async def fetch(branch: str) -> Any:
            if branch == "a":
                entered_a.set()
                await release_a.wait()
                return schema_a
            return schema_b

        mock_client.schema._fetch.side_effect = fetch

        read_a = asyncio.create_task(get_cached_branch_schema(mock_ctx, "a"))
        await entered_a.wait()  # ``a`` is inside its upstream fetch, holding ``a``'s lock

        result_b = await get_cached_branch_schema(mock_ctx, "b")

        assert result_b is schema_b
        assert not read_a.done(), "the read for `b` ran to completion while `a` still held its lock"
        release_a.set()
        assert await read_a is schema_a
        assert mock_client.schema._fetch.await_count == 2

    @pytest.mark.anyio
    async def test_a_mixed_burst_costs_one_fetch_per_branch(
        self,
        mock_ctx: MagicMock,
        mock_client: MagicMock,
    ) -> None:
        """Ten cold reads each for ``a`` and ``b``, interleaved: exactly one upstream fetch per branch."""
        schemas = {"a": _make_branch_schema(schema_hash="HA"), "b": _make_branch_schema(schema_hash="HB")}
        release = asyncio.Event()
        fetched: list[str] = []

        async def fetch(branch: str) -> Any:
            fetched.append(branch)
            await release.wait()
            return schemas[branch]

        mock_client.schema._fetch.side_effect = fetch
        branches = ["a", "b"] * 10

        tasks = [asyncio.create_task(get_cached_branch_schema(mock_ctx, branch)) for branch in branches]
        await asyncio.sleep(0)  # park every waiter on its branch's lock behind that branch's first fetch
        release.set()
        results = await asyncio.gather(*tasks)

        assert sorted(fetched) == ["a", "b"], f"expected one fetch per branch, got {fetched}"
        assert all(result is schemas[branch] for result, branch in zip(results, branches, strict=True))

    @pytest.mark.anyio
    async def test_a_hanging_probe_for_one_branch_does_not_delay_another_branch_probe(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        """``a`` is timing out upstream; ``b``, past its skip-window, probes and is served meanwhile."""
        now = schema_cache._now()
        schema_a = _make_branch_schema(schema_hash="HA")
        schema_b = _make_branch_schema(schema_hash="HB")
        app_ctx.schema_cache["a"] = _past_window_entry(schema_a, now=now, branch="a")
        app_ctx.schema_cache["b"] = _past_window_entry(schema_b, now=now, branch="b")
        entered_a = asyncio.Event()
        release_a = asyncio.Event()

        async def probe(url: str, **_: Any) -> Any:
            if urlencode([("branch", "a")]) in url:
                entered_a.set()
                await release_a.wait()
                msg = "down"
                raise httpx.NetworkError(msg)
            return _make_response(json_body={"main": "H1"})

        mock_client._get.side_effect = probe

        read_a = asyncio.create_task(get_cached_branch_schema(mock_ctx, "a"))
        await entered_a.wait()  # ``a``'s probe is in flight, holding ``a``'s lock

        result_b = await get_cached_branch_schema(mock_ctx, "b")

        assert result_b is schema_b
        assert app_ctx.schema_cache["b"].consecutive_failures == 0
        assert not read_a.done(), "the probe for `b` ran to completion while `a`'s probe still hung"
        release_a.set()
        assert await read_a is schema_a  # served stale: one failure, breaker not tripped
        assert app_ctx.schema_cache["a"].consecutive_failures == 1
        assert _summary_probes(mock_client) == 2

    @pytest.mark.anyio
    async def test_a_throttled_branch_does_not_stop_another_branch_probing(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        clock: _FakeClock,
    ) -> None:
        """``a`` inside its failure throttle serves stale without probing; ``b`` still probes."""
        now = clock.now
        schema_a = _make_branch_schema(schema_hash="HA")
        schema_b = _make_branch_schema(schema_hash="HB")
        app_ctx.schema_cache["a"] = _past_window_entry(
            schema_a,
            now=now,
            branch="a",
            consecutive_failures=1,
            last_attempt_monotonic=now - 5,  # inside the min(ttl=30, 30) s throttle
        )
        app_ctx.schema_cache["b"] = _past_window_entry(schema_b, now=now, branch="b")
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})

        assert await get_cached_branch_schema(mock_ctx, "a") is schema_a
        assert await get_cached_branch_schema(mock_ctx, "b") is schema_b

        assert _summary_probes(mock_client) == 1
        assert urlencode([("branch", "b")]) in mock_client._get.await_args.kwargs["url"]
        assert app_ctx.schema_cache["a"].consecutive_failures == 1  # untouched: ``a`` did not probe
        assert app_ctx.schema_cache["b"].consecutive_failures == 0

    @pytest.mark.anyio
    async def test_the_sdl_fill_shares_its_branch_lock_and_leaves_other_branches_alone(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        clock: _FakeClock,
    ) -> None:
        """A parked lazy SDL fill for ``a`` holds ``a``'s lock — the one its structured reads take — and no other."""
        now = clock.now
        schema_a = _make_branch_schema(schema_hash="HA")
        schema_b = _make_branch_schema(schema_hash="HB")
        app_ctx.schema_cache["a"] = CachedSchemaEntry(
            branch="a",
            schema=schema_a,
            schema_hash="H1",
            graphql_sdl=None,  # only the SDL fetch failed; the next SDL read fills it lazily
            fetched_at_monotonic=now,
            consecutive_failures=0,
            last_attempt_monotonic=now,
        )
        app_ctx.schema_cache["b"] = _past_window_entry(schema_b, now=now, branch="b")
        entered = asyncio.Event()
        release = asyncio.Event()

        async def slow_sdl(url: str) -> Any:
            del url
            entered.set()
            await release.wait()
            return _make_response(text="sdl-a")

        mock_client.sdl_get.side_effect = slow_sdl
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})

        fill_a = asyncio.create_task(get_cached_graphql_sdl(mock_ctx, "a"))
        await entered.wait()  # the fill holds ``a``'s lock across its upstream call

        assert await get_cached_branch_schema(mock_ctx, "b") is schema_b  # ``b`` probes and is served meanwhile

        clock.advance(31)  # ``a`` is now past its skip-window: its next structured read takes the lock
        read_a = asyncio.create_task(get_cached_branch_schema(mock_ctx, "a"))
        for _ in range(3):
            await asyncio.sleep(0)
        assert not read_a.done(), "a structured read for `a` must queue behind `a`'s SDL fill"
        assert not fill_a.done()

        release.set()
        assert await fill_a == "sdl-a"
        assert await read_a is schema_a
        assert app_ctx.schema_cache["a"].graphql_sdl == "sdl-a"
        assert _summary_probes(mock_client) == 2  # one for ``b``, one for ``a`` once its lock was free

    @pytest.mark.anyio
    async def test_an_unknown_branch_leaves_no_lock_behind(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        """A read for a branch that does not exist stores no entry — and keeps no lock either."""
        mock_client.schema._fetch.side_effect = BranchNotFoundError(identifier="ghost")

        for name in ("ghost-1", "ghost-2", "ghost-3"):
            with pytest.raises(BranchNotFoundError):
                await get_cached_branch_schema(mock_ctx, name)

        assert mock_client.schema._fetch.await_count == 3
        assert app_ctx.schema_cache == {}
        assert app_ctx._schema_cache_locks == {}
        assert app_ctx._schema_cache_lock_holders == {}

    @pytest.mark.anyio
    async def test_a_branch_with_an_entry_keeps_its_lock_between_reads(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        clock: _FakeClock,
    ) -> None:
        """Once a read has stored an entry, its lock stays — the same object — for the entry's revalidations."""
        schema = _make_branch_schema(schema_hash="H1")
        mock_client.schema._fetch.return_value = schema
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})

        assert await get_cached_branch_schema(mock_ctx, "a") is schema
        lock = app_ctx._schema_cache_locks["a"]
        assert app_ctx._schema_cache_lock_holders == {}  # nobody on it, yet kept: ``a`` has an entry

        clock.advance(31)  # past the skip-window: the next read takes the lock and probes
        assert await get_cached_branch_schema(mock_ctx, "a") is schema

        assert _summary_probes(mock_client) == 1
        assert app_ctx._schema_cache_locks["a"] is lock
        assert app_ctx._schema_cache_lock_holders == {}

    @pytest.mark.anyio
    async def test_a_reader_queued_behind_a_cold_fetch_shares_its_one_lock(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        """Two cold readers of one branch: one lock, counted twice, and one upstream fetch serves both."""
        schema = _make_branch_schema(schema_hash="H1")
        entered = asyncio.Event()
        release = asyncio.Event()

        async def fetch(branch: str) -> Any:
            del branch
            entered.set()
            await release.wait()
            return schema

        mock_client.schema._fetch.side_effect = fetch

        first = asyncio.create_task(get_cached_branch_schema(mock_ctx, "a"))
        await entered.wait()  # the first reader holds ``a``'s lock inside its upstream fetch
        second = asyncio.create_task(get_cached_branch_schema(mock_ctx, "a"))
        for _ in range(3):
            await asyncio.sleep(0)  # the second parks on that lock
        lock = app_ctx._schema_cache_locks["a"]

        assert list(app_ctx._schema_cache_locks) == ["a"]
        assert app_ctx._schema_cache_lock_holders == {"a": 2}
        assert not second.done()

        release.set()
        assert await first is schema
        assert await second is schema
        assert mock_client.schema._fetch.await_count == 1  # single-flight: the second was served by the first's fetch
        assert app_ctx._schema_cache_locks["a"] is lock  # kept: ``a`` has an entry now
        assert app_ctx._schema_cache_lock_holders == {}

    @pytest.mark.anyio
    async def test_a_failed_cold_fetch_keeps_the_lock_for_its_waiter_and_the_last_reader_drops_it(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        """Unknown branch, two readers: the lock outlives the first's failure while the second waits, then goes."""
        entered = [asyncio.Event(), asyncio.Event()]
        release = [asyncio.Event(), asyncio.Event()]
        calls = 0

        async def fetch(branch: str) -> NoReturn:
            nonlocal calls
            index = calls
            calls += 1
            entered[index].set()
            await release[index].wait()
            raise BranchNotFoundError(identifier=branch)

        mock_client.schema._fetch.side_effect = fetch

        first = asyncio.create_task(get_cached_branch_schema(mock_ctx, "ghost"))
        await entered[0].wait()
        second = asyncio.create_task(get_cached_branch_schema(mock_ctx, "ghost"))
        for _ in range(3):
            await asyncio.sleep(0)  # the second parks on ``ghost``'s lock
        lock = app_ctx._schema_cache_locks["ghost"]
        assert app_ctx._schema_cache_lock_holders == {"ghost": 2}
        assert not entered[1].is_set()  # the second never fetches alongside the first

        release[0].set()
        with pytest.raises(BranchNotFoundError):
            await first
        await entered[1].wait()  # the second now holds the lock, inside its own fetch
        # The first released on a branch with no entry, but the second was still queued: dropping
        # the lock there would let a third reader create a second one and fetch ``ghost`` concurrently.
        assert app_ctx._schema_cache_locks["ghost"] is lock
        assert app_ctx._schema_cache_lock_holders == {"ghost": 1}

        release[1].set()
        with pytest.raises(BranchNotFoundError):
            await second

        assert mock_client.schema._fetch.await_count == 2  # the second asked upstream itself, after the first
        assert app_ctx._schema_cache_locks == {}
        assert app_ctx._schema_cache_lock_holders == {}

    @pytest.mark.anyio
    @pytest.mark.parametrize("status_code", _BRANCH_GONE_PARAMS)
    async def test_a_branch_gone_eviction_drops_the_lock_with_the_entry(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        status_code: int,
    ) -> None:
        """A branch deleted upstream leaves neither its entry nor its lock behind."""
        schema = _make_branch_schema(schema_hash="H1")
        mock_client.schema._fetch.return_value = schema
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})
        assert await get_cached_branch_schema(mock_ctx, "a") is schema
        assert "a" in app_ctx._schema_cache_locks  # the entry keeps it

        app_ctx.schema_cache["a"] = _past_window_entry(schema, now=schema_cache._now(), branch="a")
        mock_client._get.return_value = _make_response(status_code=status_code)

        with pytest.raises(BranchNotFoundError):
            await get_cached_branch_schema(mock_ctx, "a")

        assert "a" not in app_ctx.schema_cache
        assert "a" not in app_ctx._schema_cache_locks
        assert app_ctx._schema_cache_lock_holders == {}


def _ctx_with_cap(max_branches: int) -> tuple[MagicMock, AppContext]:
    """A request context whose schema cache holds at most *max_branches* branches."""
    app_ctx = AppContext(
        client=None,
        config=_make_config(schema_cache_max_branches=max_branches),
        default_branch="main",
    )
    ctx = MagicMock()
    ctx.request_context = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    return ctx, app_ctx


class TestCacheIsBoundedByBranchCount:
    """The cache holds at most ``schema_cache_max_branches`` branches, evicting the least recently used.

    Branch names are caller input and the default ``branch_pattern`` mints
    one per session, so an unbounded cache kept a full ``BranchSchema`` — and
    that branch's SDL — for every session the process ever served: the only
    other way out is a 400/404 from ``/summary``, which needs the abandoned
    branch to be read again. Every leaked entry also pinned that branch's
    lock, since a lock is kept while its branch has an entry.

    Eviction is a memory bound, not a correctness boundary: the next read of
    an evicted branch cold-fetches it. A branch with a read in flight is
    never the victim, and evicting drops the branch's lock along with its
    entry.
    """

    @pytest.mark.anyio
    async def test_filling_past_the_cap_evicts_the_least_recently_used_branch(
        self,
        mock_client: MagicMock,
    ) -> None:
        ctx, app_ctx = _ctx_with_cap(2)
        schemas = {branch: _make_branch_schema(schema_hash=f"H{branch}") for branch in ("a", "b", "c")}

        def fetch(branch: str) -> Any:
            return schemas[branch]

        mock_client.schema._fetch.side_effect = fetch

        for branch in ("a", "b", "c"):
            assert await get_cached_branch_schema(ctx, branch) is schemas[branch]

        assert list(app_ctx.schema_cache) == ["b", "c"], "the coldest branch should have gone, the newest stayed"

    @pytest.mark.anyio
    async def test_serving_a_branch_from_cache_marks_it_used(
        self,
        mock_client: MagicMock,
    ) -> None:
        """A hot branch is not evicted for having gone unwritten: a read counts as use."""
        ctx, app_ctx = _ctx_with_cap(2)
        schemas = {branch: _make_branch_schema(schema_hash=f"H{branch}") for branch in ("a", "b", "c")}

        def fetch(branch: str) -> Any:
            return schemas[branch]

        mock_client.schema._fetch.side_effect = fetch

        await get_cached_branch_schema(ctx, "a")
        await get_cached_branch_schema(ctx, "b")
        assert await get_cached_branch_schema(ctx, "a") is schemas["a"]  # served from cache, no fetch
        assert list(app_ctx.schema_cache) == ["b", "a"]

        await get_cached_branch_schema(ctx, "c")

        assert list(app_ctx.schema_cache) == ["a", "c"], "the branch just read must outlive the colder one"
        assert mock_client.schema._fetch.await_count == 3  # a, b, c — the re-read of ``a`` was a cache hit

    @pytest.mark.anyio
    async def test_a_cap_of_zero_disables_the_bound(
        self,
        mock_client: MagicMock,
    ) -> None:
        ctx, app_ctx = _ctx_with_cap(0)
        branches = [f"branch-{index}" for index in range(12)]

        def fetch(branch: str) -> Any:
            return _make_branch_schema(schema_hash=f"H{branch}")

        mock_client.schema._fetch.side_effect = fetch

        for branch in branches:
            await get_cached_branch_schema(ctx, branch)

        assert list(app_ctx.schema_cache) == branches

    @pytest.mark.anyio
    async def test_an_evicted_branch_also_loses_its_lock(
        self,
        mock_client: MagicMock,
    ) -> None:
        """``_branch_lock`` keeps a lock while its branch has an entry, so eviction must drop it too."""
        ctx, app_ctx = _ctx_with_cap(1)

        def fetch(branch: str) -> Any:
            return _make_branch_schema(schema_hash=f"H{branch}")

        mock_client.schema._fetch.side_effect = fetch

        await get_cached_branch_schema(ctx, "a")
        assert "a" in app_ctx._schema_cache_locks  # kept for the entry's revalidations

        await get_cached_branch_schema(ctx, "b")

        assert list(app_ctx.schema_cache) == ["b"]
        assert "a" not in app_ctx._schema_cache_locks
        assert app_ctx._schema_cache_lock_holders == {}

    @pytest.mark.anyio
    async def test_a_branch_with_a_read_in_flight_is_never_the_victim(
        self,
        mock_client: MagicMock,
    ) -> None:
        """``a``'s probe hangs while ``b`` is stored: nothing is evicted until ``a``'s read lets go."""
        ctx, app_ctx = _ctx_with_cap(1)
        schema_a = _make_branch_schema(schema_hash="H1")
        schema_b = _make_branch_schema(schema_hash="HB")
        app_ctx.schema_cache["a"] = _past_window_entry(schema_a, now=schema_cache._now(), branch="a")
        entered_a = asyncio.Event()
        release_a = asyncio.Event()

        async def probe(url: str, **_: Any) -> Any:
            if urlencode([("branch", "a")]) in url:
                entered_a.set()
                await release_a.wait()
            return _make_response(json_body={"main": "H1"})

        mock_client._get.side_effect = probe
        mock_client.schema._fetch.return_value = schema_b

        read_a = asyncio.create_task(get_cached_branch_schema(ctx, "a"))
        await entered_a.wait()  # ``a``'s probe is in flight, holding ``a``'s lock

        assert await get_cached_branch_schema(ctx, "b") is schema_b
        assert sorted(app_ctx.schema_cache) == ["a", "b"], "a branch mid-fetch must not be evicted"

        release_a.set()

        assert await read_a is schema_a
        assert list(app_ctx.schema_cache) == ["a"], "the next store retries the eviction it had to skip"

    @pytest.mark.anyio
    async def test_re_reading_an_evicted_branch_fetches_it_again(
        self,
        mock_client: MagicMock,
    ) -> None:
        ctx, app_ctx = _ctx_with_cap(1)
        schemas = {branch: _make_branch_schema(schema_hash=f"H{branch}") for branch in ("a", "b")}

        def fetch(branch: str) -> Any:
            return schemas[branch]

        mock_client.schema._fetch.side_effect = fetch

        await get_cached_branch_schema(ctx, "a")
        await get_cached_branch_schema(ctx, "b")

        assert await get_cached_branch_schema(ctx, "a") is schemas["a"]
        assert list(app_ctx.schema_cache) == ["a"]
        assert [call.kwargs["branch"] for call in mock_client.schema._fetch.await_args_list] == ["a", "b", "a"]


class TestColdFailureMarkersAreBounded:
    """Cold-failure markers do not outlive the window in which they fail a read fast.

    One marker is recorded per branch whose cold fetch failed, and only a
    later *successful* cold fetch of that same branch removed it. Through an
    outage, a client walking distinct branch names — the default session
    pattern does exactly that — left one permanent marker each.
    """

    @pytest.mark.anyio
    async def test_recording_a_failure_sweeps_markers_past_the_throttle_window(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        clock: _FakeClock,
    ) -> None:
        app_ctx.schema_cache_cold_failures["expired"] = clock.now - 100  # window is min(ttl, 30) = 30 s
        app_ctx.schema_cache_cold_failures["recent"] = clock.now - 5
        mock_client.schema._fetch.side_effect = httpx.NetworkError("down")

        with pytest.raises(httpx.NetworkError):
            await get_cached_branch_schema(mock_ctx, "new")

        assert set(app_ctx.schema_cache_cold_failures) == {"recent", "new"}

    @pytest.mark.anyio
    async def test_a_read_past_the_window_drops_the_spent_marker(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        clock: _FakeClock,
    ) -> None:
        """``BranchNotFoundError`` records no marker of its own, so only the read-path drop can clear this one."""
        app_ctx.schema_cache_cold_failures["gone"] = clock.now - 100
        mock_client.schema._fetch.side_effect = BranchNotFoundError(identifier="gone")

        with pytest.raises(BranchNotFoundError):
            await get_cached_branch_schema(mock_ctx, "gone")

        assert "gone" not in app_ctx.schema_cache_cold_failures


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
        old_time = schema_cache._now() - 100  # past skip-window
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
        old_time = schema_cache._now() - 100  # past skip-window
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=old_schema,
            schema_hash="H1",
            graphql_sdl="old-sdl",
            fetched_at_monotonic=old_time,
            consecutive_failures=0,
        )

        # /api/schema/summary answers H2; /schema.graphql also goes through client._get but is routed to sdl_get.
        mock_client._get.return_value = _make_response(json_body={"main": "H2"})
        _set_sdl(mock_client, "new-sdl")
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
        old_time = schema_cache._now() - 100  # past skip-window
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
        _set_sdl(mock_client, "new-sdl")
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
        assert _summary_probes(mock_client) == 1  # the refetch also fetched the SDL through _get
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
            await schema_cache._ensure_entry(ctx=mock_ctx, client=mock_client, branch=None, force_revalidate=True)

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
        old_time = schema_cache._now() - 100  # past skip-window
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
        old_time = schema_cache._now() - 100  # past skip-window
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
    branch: str = "main",
) -> CachedSchemaEntry:
    """A warm entry for *branch* (``main`` by default) past the 30 s skip-window."""
    return CachedSchemaEntry(
        branch=branch,
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

    @pytest.mark.anyio
    @pytest.mark.parametrize("make_error", _AUTH_ERROR_FACTORIES)
    async def test_lazy_sdl_fill_auth_error_reaches_the_caller_without_arming_the_sdl_throttle(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        caplog: pytest.LogCaptureFixture,
        make_error: Callable[[], Exception],
    ) -> None:
        """The SDL fetch goes through ``client._get`` too.

        A ``login()`` or refresh refused before ``/schema.graphql`` answers
        must not stamp the shared entry; a 401/403 answered by the endpoint
        itself is the next test.
        """
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl=None,
            fetched_at_monotonic=schema_cache._now(),
            consecutive_failures=2,
        )
        _fail_sdl(mock_client, make_error())

        with caplog.at_level("WARNING", logger="infrahub_mcp.schema_cache"), pytest.raises(AuthenticationError):
            await get_cached_graphql_sdl(mock_ctx)

        entry = app_ctx.schema_cache["main"]
        assert entry.graphql_sdl is None
        assert entry.graphql_sdl_last_failure_monotonic is None  # the shared throttle was not armed
        assert entry.consecutive_failures == 2
        assert any("schema_cache_auth_error" in r.message for r in caplog.records)
        assert not any("schema_cache_sdl_fill_failure" in r.message for r in caplog.records)

        # The structured schema is unaffected and keeps being served from the cache.
        assert await get_cached_branch_schema(mock_ctx) is schema
        mock_client.schema._fetch.assert_not_awaited()

        # The next SDL reader is not failed fast: it probes upstream with its own credential.
        with pytest.raises(AuthenticationError):
            await get_cached_graphql_sdl(mock_ctx)
        assert mock_client.sdl_get.await_count == 2

    @pytest.mark.anyio
    @pytest.mark.parametrize("status_code", [httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN])
    async def test_lazy_sdl_fill_rejected_by_schema_graphql_itself_reaches_the_caller_without_arming_the_sdl_throttle(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        caplog: pytest.LogCaptureFixture,
        status_code: int,
    ) -> None:
        """A 401/403 *answered by* ``/schema.graphql`` — ``token-passthrough``, where ``login()`` is a no-op.

        The SDK's ``get_graphql_schema`` folded this into a bare ``ValueError``
        that was throttled like an outage. The local fetch calls
        ``raise_for_status()``, so it is classified like a rejection from
        ``/summary`` and the shared entry is left alone.
        """
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl=None,
            fetched_at_monotonic=schema_cache._now(),
            consecutive_failures=2,
        )
        _fail_sdl(mock_client, status_code)

        with caplog.at_level("WARNING", logger="infrahub_mcp.schema_cache"), pytest.raises(AuthenticationError):
            await get_cached_graphql_sdl(mock_ctx)

        entry = app_ctx.schema_cache["main"]
        assert entry.graphql_sdl is None
        assert entry.graphql_sdl_last_failure_monotonic is None  # the shared throttle was not armed
        assert entry.consecutive_failures == 2
        auth_logs = [r.message for r in caplog.records if "schema_cache_auth_error" in r.message]
        assert auth_logs
        assert all(f"status={int(status_code)}" in m for m in auth_logs)
        assert not any("schema_cache_sdl_fill_failure" in r.message for r in caplog.records)

        # The structured schema is unaffected and keeps being served from the cache.
        assert await get_cached_branch_schema(mock_ctx) is schema
        mock_client.schema._fetch.assert_not_awaited()

        # The next SDL reader is not failed fast: it asks upstream with its own credential.
        with pytest.raises(AuthenticationError):
            await get_cached_graphql_sdl(mock_ctx)
        assert mock_client.sdl_get.await_count == 2


# ---------------------------------------------------------------------------
# Passthrough callers are validated before a cache hit
# ---------------------------------------------------------------------------


_PASSTHROUGH_AUTH_MODES = [
    pytest.param("token-passthrough", id="token-passthrough"),
    pytest.param("basic-passthrough", id="basic-passthrough"),
]


def _ctx_for_auth_mode(auth_mode: str) -> tuple[MagicMock, AppContext]:
    """A request context whose ``AppContext`` runs in *auth_mode*."""
    app_ctx = AppContext(client=None, config=_make_config(auth_mode=auth_mode), default_branch="main")
    ctx = MagicMock()
    ctx.request_context = MagicMock()
    ctx.request_context.lifespan_context = app_ctx
    return ctx, app_ctx


def _within_window_entry(schema: MagicMock, *, now: float) -> CachedSchemaEntry:
    """A warm ``main`` entry fetched just now — a plain ``hit`` for a validated caller."""
    return _entry(schema, fetched_at_monotonic=now, last_attempt_monotonic=now)


def _probe_connect_error(client: MagicMock) -> None:
    client._get.side_effect = httpx.ConnectError("down")


def _probe_http_503(client: MagicMock) -> None:
    client._get.return_value = _make_response(status_code=httpx.codes.SERVICE_UNAVAILABLE)


_TRANSIENT_PROBE_FAILURES = [
    pytest.param(_probe_connect_error, id="connect-error"),
    pytest.param(_probe_http_503, id="http-503"),
]


class TestPassthroughCallerIsValidatedBeforeAHit:
    """In the passthrough modes a hot entry is served only to a client Infrahub has already seen.

    ``get_client`` only checks that a credential is *present*. Before this, a
    warm entry inside the skip-window was served to any caller with zero
    upstream calls, so a passthrough caller with a garbage token got the full
    schema from ``get_schema`` and the ``infrahub://schema*`` resources — and
    kept getting it for as long as other callers refreshed the entry. The
    signal that a caller has been validated is its own client's SDK cache,
    which only an upstream call on that client earlier in the same request
    primes. An unvalidated caller is never served stale either.
    """

    @pytest.mark.anyio
    @pytest.mark.parametrize("auth_mode", _PASSTHROUGH_AUTH_MODES)
    async def test_warm_read_on_an_unprimed_client_probes_with_that_client(
        self,
        mock_metrics: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        auth_mode: str,
    ) -> None:
        ctx, app_ctx = _ctx_for_auth_mode(auth_mode)
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = _within_window_entry(schema, now=schema_cache._now())

        def configure(client: MagicMock) -> None:
            client._get.return_value = _make_response(json_body={"main": "H1"})

        built = _patch_fresh_client_per_call(monkeypatch, configure=configure)

        result = await get_cached_branch_schema(ctx)

        assert result is schema
        (client,) = built
        client._get.assert_awaited_once()  # /summary, with this caller's credential
        client.schema._fetch.assert_not_awaited()  # the hash matched: no full refetch
        assert client.schema.cache["main"] is schema  # primed: validated for the rest of the request
        events = [c.args[0] for c in mock_metrics.record_schema_cache_event.call_args_list]
        assert "hash_match" in events
        assert "hit" not in events

    @pytest.mark.anyio
    @pytest.mark.parametrize("auth_mode", _PASSTHROUGH_AUTH_MODES)
    async def test_a_second_read_on_the_primed_client_makes_no_upstream_call(
        self,
        mock_metrics: MagicMock,
        auth_mode: str,
    ) -> None:
        """One probe per request: the tool's later helper calls on the same client are plain hits."""
        ctx, app_ctx = _ctx_for_auth_mode(auth_mode)
        schema = _make_branch_schema(schema_hash="H1", kinds=["InfraDevice"])
        app_ctx.schema_cache["main"] = _within_window_entry(schema, now=schema_cache._now())
        caller = _make_client()
        caller._get.return_value = _make_response(json_body={"main": "H1"})

        await get_cached_branch_schema(ctx, client=caller)
        kind = await get_cached_kind(ctx, kind="InfraDevice", client=caller)
        sdl = await get_cached_graphql_sdl(ctx, client=caller)

        assert kind is schema.nodes["InfraDevice"]
        assert sdl == "sdl"
        caller._get.assert_awaited_once()
        events = [c.args[0] for c in mock_metrics.record_schema_cache_event.call_args_list]
        assert events == ["hash_match", "hit", "hit"]

    @pytest.mark.anyio
    @pytest.mark.parametrize("auth_mode", _PASSTHROUGH_AUTH_MODES)
    @pytest.mark.parametrize("status_code", [httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN])
    async def test_a_rejected_credential_raises_to_that_caller_and_leaves_the_entry_servable(
        self,
        mock_metrics: MagicMock,
        auth_mode: str,
        status_code: int,
    ) -> None:
        ctx, app_ctx = _ctx_for_auth_mode(auth_mode)
        schema = _make_branch_schema(schema_hash="H1")
        entry = _within_window_entry(schema, now=schema_cache._now())
        app_ctx.schema_cache["main"] = entry
        bogus = _make_client()
        bogus._get.return_value = _make_response(status_code=status_code)

        with pytest.raises(AuthenticationError, match=f"HTTP {int(status_code)}"):
            await get_cached_branch_schema(ctx, client=bogus)

        bogus.schema.set_cache.assert_not_called()  # the schema never reaches the rejected caller
        assert app_ctx.schema_cache["main"] is entry  # same object: counters, timestamps and SDL untouched
        events = [c.args[0] for c in mock_metrics.record_schema_cache_event.call_args_list]
        assert "revalidate_failure" not in events
        assert "hit" not in events

        # Nothing was armed against the next caller: it is served after its own probe.
        genuine = _make_client()
        genuine._get.return_value = _make_response(json_body={"main": "H1"})
        assert await get_cached_branch_schema(ctx, client=genuine) is schema
        genuine._get.assert_awaited_once()

    @pytest.mark.anyio
    @pytest.mark.parametrize("auth_mode", _PASSTHROUGH_AUTH_MODES)
    async def test_catalog_read_with_a_garbage_token_is_refused_from_a_warm_cache(
        self,
        monkeypatch: pytest.MonkeyPatch,
        auth_mode: str,
    ) -> None:
        """The reported hole: ``get_schema`` / ``infrahub://schema`` on a warm entry with an unknown token."""
        ctx, app_ctx = _ctx_for_auth_mode(auth_mode)
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = _within_window_entry(schema, now=schema_cache._now())

        def configure(client: MagicMock) -> None:
            client._get.return_value = _make_response(status_code=httpx.codes.UNAUTHORIZED)

        built = _patch_fresh_client_per_call(monkeypatch, configure=configure)

        with pytest.raises(AuthenticationError):
            await get_schema_catalog(ctx)

        (client,) = built  # schema.py resolved one client for the read and probed with it
        client._get.assert_awaited_once()

    @pytest.mark.anyio
    @pytest.mark.parametrize("auth_mode", _PASSTHROUGH_AUTH_MODES)
    @pytest.mark.parametrize("configure", _TRANSIENT_PROBE_FAILURES)
    async def test_a_transient_probe_failure_on_an_unprimed_client_fails_closed(
        self,
        mock_metrics: MagicMock,
        clock: _FakeClock,
        auth_mode: str,
        configure: Callable[[MagicMock], None],
    ) -> None:
        """No validated credential, no schema: the caller is not served stale, but the failure still counts."""
        ctx, app_ctx = _ctx_for_auth_mode(auth_mode)
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = _within_window_entry(schema, now=clock.now)
        caller = _make_client()
        configure(caller)

        with pytest.raises(ToolError, match="credential could not be checked"):
            await get_cached_branch_schema(ctx, client=caller)

        # Two probes: the validating one outside the lock, then the lock path's own after it fell
        # through. Only the second is counted — the fast path deliberately records no failure.
        assert _summary_probes(caller) == 2
        caller.schema.set_cache.assert_not_called()
        assert app_ctx.schema_cache["main"].consecutive_failures == 1  # breaker bookkeeping still ran
        events = [c.args[0] for c in mock_metrics.record_schema_cache_event.call_args_list]
        assert events.count("revalidate_failure") == 1
        assert "stale_hit" not in events

        # Still unprimed, now inside the throttle: a further read in this request fails fast, no probe.
        clock.advance(1)
        with pytest.raises(ToolError, match="cannot be checked until the next upstream attempt"):
            await get_cached_branch_schema(ctx, client=caller)
        assert _summary_probes(caller) == 2

    @pytest.mark.anyio
    @pytest.mark.parametrize("auth_mode", _PASSTHROUGH_AUTH_MODES)
    async def test_an_unprimed_client_inside_the_failure_throttle_fails_fast_without_probing(
        self,
        mock_metrics: MagicMock,
        clock: _FakeClock,
        auth_mode: str,
    ) -> None:
        """Another caller's probe failed moments ago: neither stale schema nor a probe for this one."""
        ctx, app_ctx = _ctx_for_auth_mode(auth_mode)
        schema = _make_branch_schema(schema_hash="H1")
        entry = _entry(
            schema,
            fetched_at_monotonic=clock.now - 100,  # past the skip-window
            consecutive_failures=1,
            last_attempt_monotonic=clock.now - 5,  # failed probe inside the 30 s throttle
        )
        app_ctx.schema_cache["main"] = entry
        caller = _make_client()
        caller._get.side_effect = httpx.NetworkError("down")

        with pytest.raises(ToolError, match="cannot be checked until the next upstream attempt in 25 s"):
            await get_cached_branch_schema(ctx, client=caller)

        caller._get.assert_not_awaited()
        caller.schema.set_cache.assert_not_called()
        assert app_ctx.schema_cache["main"] is entry
        events = [c.args[0] for c in mock_metrics.record_schema_cache_event.call_args_list]
        assert "stale_hit" not in events

    @pytest.mark.anyio
    @pytest.mark.parametrize("auth_mode", _PASSTHROUGH_AUTH_MODES)
    async def test_the_throttle_wins_over_the_skip_window_for_an_unprimed_client(
        self,
        clock: _FakeClock,
        auth_mode: str,
    ) -> None:
        """A forced probe can fail inside the skip-window; the window must not route this caller to a probe."""
        ctx, app_ctx = _ctx_for_auth_mode(auth_mode)
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = _entry(
            schema,
            fetched_at_monotonic=clock.now - 10,  # inside the skip-window
            consecutive_failures=1,
            last_attempt_monotonic=clock.now - 5,  # a forced probe failed since
        )
        caller = _make_client()
        caller._get.side_effect = httpx.NetworkError("down")

        with pytest.raises(ToolError):
            await get_cached_branch_schema(ctx, client=caller)

        caller._get.assert_not_awaited()

    @pytest.mark.anyio
    @pytest.mark.parametrize("auth_mode", _PASSTHROUGH_AUTH_MODES)
    async def test_a_client_validated_this_request_is_still_served_stale_on_a_transient_failure(
        self,
        clock: _FakeClock,
        auth_mode: str,
    ) -> None:
        """The fail-closed residual is for unvalidated callers only; a primed client keeps the stale-serving."""
        ctx, app_ctx = _ctx_for_auth_mode(auth_mode)
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = _within_window_entry(schema, now=clock.now)
        caller = _make_client()
        caller._get.return_value = _make_response(json_body={"main": "H1"})
        await get_cached_branch_schema(ctx, client=caller)  # validated and primed

        clock.advance(31)  # past the skip-window
        caller._get.side_effect = httpx.NetworkError("down")
        result = await get_cached_branch_schema(ctx, client=caller)

        assert result is schema
        assert caller._get.await_count == 2
        assert app_ctx.schema_cache["main"].consecutive_failures == 1

    @pytest.mark.anyio
    @pytest.mark.parametrize("auth_mode", _PASSTHROUGH_AUTH_MODES)
    async def test_a_kind_miss_costs_the_request_one_probe_in_total(
        self,
        clock: _FakeClock,
        auth_mode: str,
    ) -> None:
        """The validating probe arms the forced-revalidation debounce, so the miss does not probe again."""
        ctx, app_ctx = _ctx_for_auth_mode(auth_mode)
        schema = _make_branch_schema(schema_hash="H1", kinds=["InfraDevice"])
        app_ctx.schema_cache["main"] = _entry(
            schema,
            fetched_at_monotonic=clock.now - 10,
            last_attempt_monotonic=clock.now - 10,  # past the 2 s debounce: a miss on its own would probe
        )
        caller = _make_client()
        caller._get.return_value = _make_response(json_body={"main": "H1"})

        with pytest.raises(SchemaNotFoundError):
            await get_cached_kind(ctx, kind="GhostKind", client=caller)
        clock.advance(1)
        with pytest.raises(SchemaNotFoundError):
            await get_cached_kind(ctx, kind="OtherGhost", client=caller)

        caller._get.assert_awaited_once()
        caller.schema._fetch.assert_not_awaited()

    @pytest.mark.anyio
    async def test_shared_credential_modes_keep_serving_a_warm_entry_with_zero_upstream_calls(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_metrics: MagicMock,
    ) -> None:
        """Contrast, ``auth_mode="none"``: the lifespan client's credential is the server's own.

        ``TestPrimedClientIsTheCallers`` covers the priming side of this read.
        """
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = _within_window_entry(schema, now=schema_cache._now())
        caller = _make_client()  # unprimed, as a fresh client would be

        result = await get_cached_branch_schema(mock_ctx, client=caller)

        assert result is schema
        caller._get.assert_not_awaited()
        assert caller.schema.cache["main"] is schema
        events = [c.args[0] for c in mock_metrics.record_schema_cache_event.call_args_list]
        assert events == ["hit"]


class TestPassthroughProbesRunOutsideTheBranchLock:
    """An unvalidated passthrough caller checks its credential before taking the branch lock.

    Its ``/summary`` probe carries its own credential, so N concurrent
    callers on one branch cannot be coalesced into one probe. Run under the
    lock they were N *sequential* probes, each waiting out every earlier
    caller's round-trip, where the pre-cache baseline issued its heavier
    ``/api/schema`` fetches concurrently. The probe therefore runs outside
    the lock whenever there is a warm, unbroken entry to compare against;
    only the shared work — a cold fetch, or the refetch a hash difference
    triggers — still queues behind the lock.
    """

    @staticmethod
    def _gated_probe(client: MagicMock, gate: asyncio.Event, entered: list[MagicMock]) -> None:
        """Park *client*'s ``/summary`` probe on *gate*, recording the client that reached it."""

        async def probe(url: str, **_: Any) -> Any:
            if _SDL_PATH in url:
                return await client.sdl_get(url=url)
            entered.append(client)
            await gate.wait()
            return _make_response(json_body={"main": "H1"})

        client._get.side_effect = probe

    @pytest.mark.anyio
    @pytest.mark.parametrize("auth_mode", _PASSTHROUGH_AUTH_MODES)
    async def test_concurrent_unprimed_callers_probe_simultaneously_without_the_lock(
        self,
        auth_mode: str,
    ) -> None:
        """The point of the change: five callers, five probes in flight at once, no lock taken."""
        ctx, app_ctx = _ctx_for_auth_mode(auth_mode)
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = _within_window_entry(schema, now=schema_cache._now())

        gate = asyncio.Event()
        entered: list[MagicMock] = []
        callers = [_make_client() for _ in range(5)]
        for caller in callers:
            self._gated_probe(caller, gate, entered)

        tasks = [asyncio.create_task(get_cached_branch_schema(ctx, client=caller)) for caller in callers]
        for _ in range(20):  # yield until every caller has reached its own probe
            if len(entered) == len(callers):
                break
            await asyncio.sleep(0)

        assert len(entered) == 5, f"probes in flight: {len(entered)} — they are serializing"
        assert not any(task.done() for task in tasks)  # all five parked on their own probe, none served yet
        assert not app_ctx._schema_cache_lock_holders  # no reader took or queued on the branch lock

        gate.set()
        results = await asyncio.gather(*tasks)

        assert all(result is schema for result in results)
        assert all(caller.schema.cache["main"] is schema for caller in callers)  # each primed for its request
        assert all(_summary_probes(caller) == 1 for caller in callers)
        assert all(caller.schema._fetch.await_count == 0 for caller in callers)  # hash matched: no refetch
        assert not app_ctx._schema_cache_lock_holders

    @pytest.mark.anyio
    @pytest.mark.parametrize("auth_mode", _PASSTHROUGH_AUTH_MODES)
    @pytest.mark.parametrize("status_code", [httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN])
    async def test_a_rejected_credential_outside_the_lock_leaves_the_entry_untouched(
        self,
        mock_metrics: MagicMock,
        auth_mode: str,
        status_code: int,
    ) -> None:
        """Caller-scoped, exactly as under the lock: no counter moves and the caller stays unprimed."""
        ctx, passthrough_ctx = _ctx_for_auth_mode(auth_mode)
        schema = _make_branch_schema(schema_hash="H1")
        entry = _within_window_entry(schema, now=schema_cache._now())
        passthrough_ctx.schema_cache["main"] = entry
        bogus = _make_client()
        bogus._get.return_value = _make_response(status_code=status_code)

        with pytest.raises(AuthenticationError, match=f"HTTP {int(status_code)}"):
            await get_cached_branch_schema(ctx, client=bogus)

        assert passthrough_ctx.schema_cache["main"] is entry  # same object: counters and timestamps untouched
        assert entry.consecutive_failures == 0
        bogus.schema.set_cache.assert_not_called()
        assert not passthrough_ctx._schema_cache_lock_holders
        events = [c.args[0] for c in mock_metrics.record_schema_cache_event.call_args_list]
        assert "revalidate_failure" not in events

    @pytest.mark.anyio
    @pytest.mark.parametrize("auth_mode", _PASSTHROUGH_AUTH_MODES)
    @pytest.mark.parametrize("status_code", _BRANCH_GONE_PARAMS)
    async def test_a_branch_gone_outside_the_lock_evicts_and_raises(
        self,
        auth_mode: str,
        status_code: int,
    ) -> None:
        ctx, app_ctx = _ctx_for_auth_mode(auth_mode)
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = _within_window_entry(schema, now=schema_cache._now())
        caller = _make_client()
        caller._get.return_value = _make_response(status_code=status_code)

        with pytest.raises(BranchNotFoundError):
            await get_cached_branch_schema(ctx, client=caller)

        assert "main" not in app_ctx.schema_cache
        caller.schema.set_cache.assert_not_called()

    @pytest.mark.anyio
    @pytest.mark.parametrize("auth_mode", _PASSTHROUGH_AUTH_MODES)
    @pytest.mark.parametrize("configure", _TRANSIENT_PROBE_FAILURES)
    async def test_a_transient_probe_failure_falls_through_to_the_lock_and_counts_once(
        self,
        mock_metrics: MagicMock,
        clock: _FakeClock,
        auth_mode: str,
        configure: Callable[[MagicMock], None],
    ) -> None:
        """The fast path records nothing; the lock path owns the bookkeeping and the caller fails closed."""
        ctx, app_ctx = _ctx_for_auth_mode(auth_mode)
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = _within_window_entry(schema, now=clock.now)
        caller = _make_client()
        configure(caller)

        with pytest.raises(ToolError, match="credential could not be checked"):
            await get_cached_branch_schema(ctx, client=caller)

        assert _summary_probes(caller) == 2  # once outside the lock, once under it
        assert app_ctx.schema_cache["main"].consecutive_failures == 1  # counted exactly once
        caller.schema.set_cache.assert_not_called()
        events = [c.args[0] for c in mock_metrics.record_schema_cache_event.call_args_list]
        assert events.count("revalidate_failure") == 1
        assert "stale_hit" not in events

    @pytest.mark.anyio
    @pytest.mark.parametrize("auth_mode", _PASSTHROUGH_AUTH_MODES)
    async def test_a_hash_difference_refetches_under_the_lock(
        self,
        mock_metrics: MagicMock,
        auth_mode: str,
    ) -> None:
        """The refetch is shared work: the fast path declines and the lock path serves the new schema."""
        ctx, app_ctx = _ctx_for_auth_mode(auth_mode)
        old = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = _within_window_entry(old, now=schema_cache._now())
        new = _make_branch_schema(schema_hash="H2", kinds=["InfraDevice"])
        caller = _make_client()
        caller._get.return_value = _make_response(json_body={"main": "H2"})
        caller.schema._fetch.return_value = new

        result = await get_cached_branch_schema(ctx, client=caller)

        assert result is new
        assert app_ctx.schema_cache["main"].schema_hash == "H2"
        assert _summary_probes(caller) == 2  # the fast-path probe, then the lock path's own
        caller.schema._fetch.assert_awaited_once_with(branch="main")
        assert caller.schema.cache["main"] is new
        events = [c.args[0] for c in mock_metrics.record_schema_cache_event.call_args_list]
        assert "hash_diff" in events
        assert "hash_match" not in events

    @pytest.mark.anyio
    @pytest.mark.parametrize("auth_mode", _PASSTHROUGH_AUTH_MODES)
    async def test_a_circuit_broken_entry_still_takes_the_lock_path(
        self,
        clock: _FakeClock,
        auth_mode: str,
    ) -> None:
        """A recovery probe carries breaker bookkeeping, so the fast path is skipped for a broken entry."""
        ctx, app_ctx = _ctx_for_auth_mode(auth_mode)
        app_ctx.config = _make_config(auth_mode=auth_mode, schema_cache_max_consecutive_failures=2)
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = _entry(
            schema,
            fetched_at_monotonic=clock.now - 100,
            consecutive_failures=2,  # broken
            last_attempt_monotonic=clock.now - 100,  # past the throttle: a recovery probe is due
        )
        caller = _make_client()
        caller._get.return_value = _make_response(json_body={"main": "H1"})
        held: list[int] = []

        original = schema_cache._revalidate_under_lock

        async def recording_revalidate(**kwargs: Any) -> Any:
            held.append(app_ctx._schema_cache_lock_holders.get("main", 0))
            return await original(**kwargs)

        with patch.object(schema_cache, "_revalidate_under_lock", recording_revalidate):
            result = await get_cached_branch_schema(ctx, client=caller)

        assert result is schema
        assert held == [1]  # the probe ran with the branch lock held
        assert _summary_probes(caller) == 1  # only the lock path's recovery probe: the fast path never ran
        assert app_ctx.schema_cache["main"].consecutive_failures == 0  # healed


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
        _set_sdl(mock_client, "new-sdl")

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
        mock_metrics: MagicMock,
    ) -> None:
        app_ctx.config = _make_config(
            schema_cache_max_consecutive_failures=0,
            schema_cache_max_staleness_seconds=0,
        )
        schema = _make_branch_schema(schema_hash="H1")
        now = schema_cache._now()
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=now - 100_000,
            consecutive_failures=999,
            last_attempt_monotonic=now - 60,  # past the probe throttle, so this read probes
            failing_since_monotonic=now - 100_000,  # a streak far past any staleness ceiling
        )
        mock_client._get.side_effect = httpx.NetworkError("still down")

        result = await get_cached_branch_schema(mock_ctx)

        # Both thresholds disabled — serve stale even after an extreme failure
        # count and a streak of extreme length, and never count a trip.
        assert result is schema
        assert app_ctx.schema_cache["main"].consecutive_failures == 1000
        assert not any(c.args[0] == "circuit_break" for c in mock_metrics.record_schema_cache_event.call_args_list)

    @pytest.mark.anyio
    async def test_successful_revalidation_resets_failure_counter(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        old_time = schema_cache._now() - 100  # past skip-window
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
    async def test_idle_entry_is_served_stale_on_its_first_transient_failure(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        mock_metrics: MagicMock,
        clock: _FakeClock,
    ) -> None:
        """Idle time does not count toward ``max_staleness``.

        Default config, no schema traffic for well over 900 s. The next read's
        single probe hits one transient blip. Measured from the last success
        the entry would already be "past" the ceiling and this one failure
        would fail it closed; measured from the first failure of the streak it
        is served stale, exactly like a blip on a busy branch.
        """
        clock.advance(20_000)
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=clock.now - 10_000,  # idle far past max_staleness
            last_attempt_monotonic=clock.now - 10_000,
            consecutive_failures=0,
        )
        mock_client._get.side_effect = httpx.NetworkError("blip")

        result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        mock_client._get.assert_awaited_once()
        entry = app_ctx.schema_cache["main"]
        assert entry.consecutive_failures == 1
        assert entry.failing_since_monotonic == clock.now
        assert entry.circuit_break_recorded is False
        assert not any(c.args[0] == "circuit_break" for c in mock_metrics.record_schema_cache_event.call_args_list)

    @pytest.mark.anyio
    async def test_streak_older_than_max_staleness_fails_closed_on_the_next_failed_probe(  # noqa: PLR0913, PLR0917
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        mock_metrics: MagicMock,
        clock: _FakeClock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The staleness threshold bounds how long a streak may serve stale.

        The streak's first failure was ``max_staleness`` ago and it is still
        under the consecutive-failures threshold, so this probe's failure trips
        the breaker on staleness alone — and the trip is counted exactly once.
        """
        clock.advance(20_000)
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=_make_branch_schema(schema_hash="H1"),
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=clock.now - 1_000,
            consecutive_failures=3,  # well under max_consecutive_failures=10
            last_attempt_monotonic=clock.now - 60,  # past the probe throttle
            failing_since_monotonic=clock.now - 900,  # streak as old as max_staleness
        )
        mock_client._get.side_effect = httpx.NetworkError("still down")

        with (
            caplog.at_level("ERROR", logger="infrahub_mcp.schema_cache"),
            pytest.raises(ToolError, match="circuit-break threshold"),
        ):
            await get_cached_branch_schema(mock_ctx)

        breaks = [c for c in mock_metrics.record_schema_cache_event.call_args_list if c.args[0] == "circuit_break"]
        assert len(breaks) == 1
        trips = [r.message for r in caplog.records if "schema_cache_circuit_break" in r.message]
        assert len(trips) == 1
        assert "threshold=max_staleness" in trips[0]
        assert "failing_for_seconds=900.0" in trips[0]
        entry = app_ctx.schema_cache["main"]
        assert entry.circuit_break_recorded is True
        assert entry.failing_since_monotonic == clock.now - 900  # carried forward, not restarted

    @pytest.mark.anyio
    async def test_successful_revalidation_ends_the_streak_so_a_later_blip_is_served_stale(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        mock_metrics: MagicMock,
        clock: _FakeClock,
    ) -> None:
        """A hash match clears ``failing_since_monotonic`` along with the counter.

        Without that reset the old streak's start would keep counting, and a
        single blip long after recovery would trip the breaker on staleness.
        """
        clock.advance(20_000)
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=clock.now - 1_000,
            consecutive_failures=5,
            last_attempt_monotonic=clock.now - 60,
            failing_since_monotonic=clock.now - 800,  # a streak, still under max_staleness
        )
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})

        await get_cached_branch_schema(mock_ctx)

        healed = app_ctx.schema_cache["main"]
        assert healed.consecutive_failures == 0
        assert healed.failing_since_monotonic is None

        # Long idle, then one blip: a fresh streak starts now and is served stale.
        clock.advance(5_000)
        mock_client._get.side_effect = httpx.NetworkError("blip")

        result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        entry = app_ctx.schema_cache["main"]
        assert entry.consecutive_failures == 1
        assert entry.failing_since_monotonic == clock.now
        assert not any(c.args[0] == "circuit_break" for c in mock_metrics.record_schema_cache_event.call_args_list)

    @pytest.mark.anyio
    async def test_max_staleness_zero_disables_the_streak_clause_alone(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        mock_metrics: MagicMock,
        clock: _FakeClock,
    ) -> None:
        """With the staleness threshold off, only the failure count can trip the breaker."""
        app_ctx.config = _make_config(schema_cache_max_staleness_seconds=0)
        clock.advance(20_000)
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=clock.now - 10_000,
            consecutive_failures=3,
            last_attempt_monotonic=clock.now - 60,
            failing_since_monotonic=clock.now - 10_000,  # would trip any positive ceiling
        )
        mock_client._get.side_effect = httpx.NetworkError("still down")

        result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        assert app_ctx.schema_cache["main"].consecutive_failures == 4
        assert not any(c.args[0] == "circuit_break" for c in mock_metrics.record_schema_cache_event.call_args_list)

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
        _set_sdl(mock_client, "schema { Query }")

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
        old_time = schema_cache._now() - 100  # past skip-window
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=old_schema,
            schema_hash="H1",
            graphql_sdl="old-sdl",
            fetched_at_monotonic=old_time,
            consecutive_failures=0,
        )
        mock_client._get.return_value = _make_response(json_body={"main": "H2"})
        _set_sdl(mock_client, "new-sdl")
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
        _set_sdl(mock_client, "branch-sdl")

        sdl = await get_cached_graphql_sdl(mock_ctx, branch="feature-x")

        assert sdl == "branch-sdl"
        mock_client.sdl_get.assert_awaited_once_with(url=_sdl_url(mock_client, "feature-x"))
        assert app_ctx.schema_cache["feature-x"].graphql_sdl == "branch-sdl"

    @pytest.mark.anyio
    async def test_disabled_cache_still_fetches_sdl_for_the_requested_branch(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        app_ctx.config = _make_config(schema_cache_enabled=False)
        _set_sdl(mock_client, "branch-sdl")

        sdl = await get_cached_graphql_sdl(mock_ctx, branch="feature-x")

        assert sdl == "branch-sdl"
        mock_client.sdl_get.assert_awaited_once_with(url=_sdl_url(mock_client, "feature-x"))

    @pytest.mark.anyio
    async def test_sdl_url_encodes_branch_name(self, mock_client: MagicMock) -> None:
        """The ``/schema.graphql`` twin of ``test_summary_url_encodes_branch_name``.

        The SDK's ``get_graphql_schema`` interpolates the branch raw: ``#``
        would drop the query as a fragment and ``&`` split it, so Infrahub
        would answer with the default branch's SDL and it would be stored as
        this branch's. The fetch builds the URL locally with ``urlencode``.
        """
        _set_sdl(mock_client, "branch-sdl")

        result = await schema_cache._fetch_graphql_sdl(mock_client, "fix#123&x=y/sub")

        assert result == "branch-sdl"
        mock_client._get.assert_awaited_once_with(
            url="http://infrahub.test/schema.graphql?branch=fix%23123%26x%3Dy%2Fsub"
        )

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
        _fail_sdl(mock_client, httpx.codes.BAD_GATEWAY)

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
        _fail_sdl(mock_client, httpx.ConnectError("down"))

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
        _fail_sdl(mock_client, httpx.ConnectError("down"))
        await get_cached_branch_schema(mock_ctx)
        assert app_ctx.schema_cache["main"].graphql_sdl is None

        # The SDL endpoint recovers: the first SDL read fills the entry, the second is a pure hit.
        _set_sdl(mock_client, "schema { Query }")

        first = await get_cached_graphql_sdl(mock_ctx)
        second = await get_cached_graphql_sdl(mock_ctx)

        assert first == second == "schema { Query }"
        assert app_ctx.schema_cache["main"].graphql_sdl == "schema { Query }"
        assert app_ctx.schema_cache["main"].schema is schema  # the fill amended the entry, it did not replace it
        assert mock_client.sdl_get.await_count == 2  # one failed cold attempt + one lazy fill
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
        _fail_sdl(mock_client, httpx.ConnectError("still down"))

        with pytest.raises(httpx.ConnectError, match="still down"):
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
        _fail_sdl(mock_client, httpx.ConnectError("down"))

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

        async def slow_sdl(*, url: str) -> MagicMock:
            await release.wait()
            return _make_response(text=f"sdl-{url.rsplit('=', 1)[1]}")

        mock_client.sdl_get.side_effect = slow_sdl

        tasks = [asyncio.create_task(get_cached_graphql_sdl(mock_ctx)) for _ in range(10)]
        await asyncio.sleep(0)  # park every reader on the cache lock behind the first fill
        release.set()
        results = await asyncio.gather(*tasks)

        assert results == ["sdl-main"] * 10
        assert mock_client.sdl_get.await_count == 1

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
        _fail_sdl(mock_client, httpx.ConnectError("still down"))

        with pytest.raises(httpx.ConnectError, match="still down"):
            await get_cached_graphql_sdl(mock_ctx)
        assert app_ctx.schema_cache["main"].graphql_sdl_last_failure_monotonic == clock.now

        clock.advance(5)
        with pytest.raises(ToolError, match=r"GraphQL SDL fetch failed 5 s ago.*next upstream attempt is in 25 s"):
            await get_cached_graphql_sdl(mock_ctx)

        mock_client.sdl_get.assert_awaited_once()  # the second read never went upstream

    @pytest.mark.anyio
    async def test_non_auth_http_error_from_schema_graphql_during_the_lazy_fill_is_transient(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
        clock: _FakeClock,
    ) -> None:
        """Only 401/403 is caller-scoped: a 503 from ``/schema.graphql`` fails this read and arms the SDL throttle."""
        schema = _make_branch_schema(schema_hash="H1")
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl=None,
            fetched_at_monotonic=clock.now,
        )
        _fail_sdl(mock_client, httpx.codes.SERVICE_UNAVAILABLE)

        with pytest.raises(httpx.HTTPStatusError):
            await get_cached_graphql_sdl(mock_ctx)

        stamped = app_ctx.schema_cache["main"]
        assert stamped.graphql_sdl_last_failure_monotonic == clock.now  # the SDL fill throttle is armed
        assert stamped.consecutive_failures == 0  # nothing counted toward the breaker

        clock.advance(5)
        with pytest.raises(ToolError, match=r"GraphQL SDL fetch failed 5 s ago"):
            await get_cached_graphql_sdl(mock_ctx)
        mock_client.sdl_get.assert_awaited_once()  # the second read never went upstream

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
        _fail_sdl(mock_client, httpx.ConnectError("down"))
        with pytest.raises(httpx.ConnectError, match="down"):
            await get_cached_graphql_sdl(mock_ctx)

        clock.advance(31)  # past the 30 s throttle, still inside the 60 s skip-window
        _set_sdl(mock_client, "schema { Query }")

        first = await get_cached_graphql_sdl(mock_ctx)
        second = await get_cached_graphql_sdl(mock_ctx)

        assert first == second == "schema { Query }"
        assert app_ctx.schema_cache["main"].graphql_sdl == "schema { Query }"
        assert mock_client.sdl_get.await_count == 2  # one failed fill + one successful fill
        assert _summary_probes(mock_client) == 0  # the structured schema never left the skip-window

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
        _fail_sdl(mock_client, httpx.ConnectError("down"))

        for _ in range(3):
            with pytest.raises(httpx.ConnectError, match="down"):
                await get_cached_graphql_sdl(mock_ctx)

        assert mock_client.sdl_get.await_count == 3

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
        _fail_sdl(mock_client, httpx.ConnectError("down"))
        with pytest.raises(httpx.ConnectError, match="down"):
            await get_cached_graphql_sdl(mock_ctx)

        clock.advance(5)
        result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        entry = app_ctx.schema_cache["main"]
        assert entry.consecutive_failures == 0
        assert entry.graphql_sdl_last_failure_monotonic == clock.now - 5
        assert _summary_probes(mock_client) == 0  # inside the skip-window: the SDL stamp forces no probe
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
