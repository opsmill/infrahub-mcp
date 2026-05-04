"""Tests for the hash-validated schema cache (``schema_cache.py``)."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastmcp.exceptions import ToolError

from infrahub_mcp import schema_cache
from infrahub_mcp.config import ServerConfig
from infrahub_mcp.schema_cache import (
    CachedSchemaEntry,
    _BranchGoneError,
    get_cached_branch_schema,
    get_cached_graphql_sdl,
    get_cached_kind,
)
from infrahub_mcp.utils import AppContext

if TYPE_CHECKING:
    pass


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


@pytest.fixture
def mock_client() -> MagicMock:
    client = MagicMock()
    client.address = "http://infrahub.test"
    client.schema = MagicMock()
    client.schema.fetch = AsyncMock()
    client.schema.set_cache = MagicMock()
    client._get = AsyncMock()  # noqa: SLF001
    return client


@pytest.fixture
def app_ctx(monkeypatch: pytest.MonkeyPatch) -> AppContext:
    config = _make_config()
    ctx = AppContext(client=None, config=config, default_branch="main")
    return ctx


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

    async def fake_default_branch(_ctx: Any) -> str:
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
        mock_client.schema.fetch.return_value = schema
        mock_client._get.return_value = _make_response(text="schema { Query }")

        result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        assert "main" in app_ctx.schema_cache
        assert app_ctx.schema_cache["main"].schema_hash == "H1"
        mock_client.schema.fetch.assert_awaited_once_with(branch="main", populate_cache=True)
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
            fetched_at_monotonic=schema_cache._now(),  # noqa: SLF001
            consecutive_failures=0,
        )

        result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        mock_client.schema.fetch.assert_not_awaited()
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
        mock_client.schema.fetch.return_value = schema

        result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        assert "main" not in app_ctx.schema_cache  # nothing cached
        mock_client.schema.fetch.assert_awaited_once_with(branch="main", populate_cache=True)


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

        async def slow_fetch(branch: str, populate_cache: bool = True) -> Any:  # noqa: ARG001
            nonlocal call_count
            call_count += 1
            await slow_event.wait()
            return schema

        mock_client.schema.fetch.side_effect = slow_fetch
        mock_client._get.return_value = _make_response(text="sdl")

        async def runner() -> Any:
            return await get_cached_branch_schema(mock_ctx)

        tasks = [asyncio.create_task(runner()) for _ in range(10)]
        await asyncio.sleep(0)  # let all coroutines park on the lock
        slow_event.set()
        results = await asyncio.gather(*tasks)

        assert all(r is schema for r in results)
        assert call_count == 1, "expected exactly one upstream fetch under burst, got {0}".format(call_count)


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
        old_time = schema_cache._now() - 100  # noqa: SLF001  # past skip-window, under staleness ceiling
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
        mock_client.schema.fetch.assert_not_awaited()
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
        old_time = schema_cache._now() - 100  # noqa: SLF001  # past skip-window, under staleness ceiling
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=old_schema,
            schema_hash="H1",
            graphql_sdl="old-sdl",
            fetched_at_monotonic=old_time,
            consecutive_failures=0,
        )

        # First _get is for /api/schema/summary, second is for /schema.graphql
        mock_client._get.side_effect = [
            _make_response(json_body={"main": "H2"}),
            _make_response(text="new-sdl"),
        ]
        mock_client.schema.fetch.return_value = new_schema

        result = await get_cached_branch_schema(mock_ctx)

        assert result is new_schema
        assert app_ctx.schema_cache["main"].schema_hash == "H2"
        assert app_ctx.schema_cache["main"].graphql_sdl == "new-sdl"
        mock_client.schema.fetch.assert_awaited_once()
        mock_metrics.record_schema_cache_event.assert_any_call("hash_diff")

    @pytest.mark.anyio
    async def test_branch_gone_evicts_entry(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        old_time = schema_cache._now() - 100  # noqa: SLF001  # past skip-window, under staleness ceiling
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=old_time,
            consecutive_failures=0,
        )
        mock_client._get.return_value = _make_response(status_code=httpx.codes.NOT_FOUND)

        with pytest.raises(_BranchGoneError):
            await get_cached_branch_schema(mock_ctx)

        assert "main" not in app_ctx.schema_cache


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
            fetched_at_monotonic=schema_cache._now(),  # noqa: SLF001
            consecutive_failures=0,
        )

        kind = await get_cached_kind(mock_ctx, kind="InfraDevice")

        assert kind is schema.nodes["InfraDevice"]
        mock_client.schema.fetch.assert_not_awaited()

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
            fetched_at_monotonic=schema_cache._now(),  # noqa: SLF001
            consecutive_failures=0,
        )

        # Missing kind triggers force_revalidate path: /summary returns same hash,
        # so no full refetch — schema stays the same — kind still missing.
        mock_client._get.return_value = _make_response(json_body={"main": "H1"})

        from infrahub_sdk.exceptions import SchemaNotFoundError

        with pytest.raises(SchemaNotFoundError):
            await get_cached_kind(mock_ctx, kind="GhostKind")

        # Full schema fetch should NOT have been called (hash matched).
        mock_client.schema.fetch.assert_not_awaited()

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
            fetched_at_monotonic=schema_cache._now(),  # noqa: SLF001
            consecutive_failures=0,
        )

        mock_client._get.side_effect = [
            _make_response(json_body={"main": "H2"}),
            _make_response(text="new-sdl"),
        ]
        mock_client.schema.fetch.return_value = new_schema

        kind = await get_cached_kind(mock_ctx, kind="NewKind")

        assert kind is new_schema.nodes["NewKind"]
        mock_client.schema.fetch.assert_awaited_once()


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
        old_time = schema_cache._now() - 100  # noqa: SLF001  # past skip-window, under staleness ceiling
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
        old_time = schema_cache._now() - 100  # noqa: SLF001  # past skip-window, under staleness ceiling
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=old_time,
            consecutive_failures=0,
        )
        mock_client._get.return_value = _make_response(json_body={"main": "H2"})
        mock_client.schema.fetch.side_effect = httpx.NetworkError("refetch-boom")

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
        mock_client.schema.fetch.side_effect = httpx.NetworkError("boom")

        with pytest.raises(httpx.NetworkError):
            await get_cached_branch_schema(mock_ctx)

        assert "main" not in app_ctx.schema_cache

    @pytest.mark.anyio
    async def test_auth_error_during_revalidation_serves_stale(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
        mock_client: MagicMock,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        old_time = schema_cache._now() - 100  # noqa: SLF001  # past skip-window, under staleness ceiling
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=old_time,
            consecutive_failures=0,
        )
        # 401 → handled uniformly with other transient failures.
        mock_client._get.return_value = _make_response(status_code=401)

        result = await get_cached_branch_schema(mock_ctx)

        assert result is schema
        assert app_ctx.schema_cache["main"].consecutive_failures == 1


class TestCircuitBreak:
    @pytest.mark.anyio
    async def test_consecutive_failure_threshold_triggers_circuit_break(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        # 10 consecutive failures already, next read fails closed.
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=schema_cache._now(),  # noqa: SLF001
            consecutive_failures=10,
        )

        with pytest.raises(ToolError, match="circuit-break threshold"):
            await get_cached_branch_schema(mock_ctx)

    @pytest.mark.anyio
    async def test_absolute_staleness_threshold_triggers_circuit_break(
        self,
        mock_ctx: MagicMock,
        app_ctx: AppContext,
    ) -> None:
        schema = _make_branch_schema(schema_hash="H1")
        # last success > max_staleness ago.
        very_old = schema_cache._now() - 10_000  # noqa: SLF001
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=schema,
            schema_hash="H1",
            graphql_sdl="sdl",
            fetched_at_monotonic=very_old,
            consecutive_failures=0,
        )

        with pytest.raises(ToolError, match="circuit-break threshold"):
            await get_cached_branch_schema(mock_ctx)

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
            fetched_at_monotonic=schema_cache._now() - 100_000,  # noqa: SLF001
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
        old_time = schema_cache._now() - 100  # noqa: SLF001  # past skip-window, under staleness ceiling
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
        mock_client.schema.fetch.return_value = schema
        mock_client._get.return_value = _make_response(text="sdl")
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
            fetched_at_monotonic=schema_cache._now() - 100,  # noqa: SLF001
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
        from infrahub_mcp.middleware import MetricsMiddleware

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

    def test_prometheus_text_includes_schema_cache_counters(self) -> None:
        from infrahub_mcp.middleware import MetricsMiddleware

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
        mock_client.schema.fetch.return_value = schema
        mock_client._get.return_value = _make_response(text="schema { Query }")

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
        old_time = schema_cache._now() - 100  # noqa: SLF001  # past skip-window, under staleness ceiling
        app_ctx.schema_cache["main"] = CachedSchemaEntry(
            branch="main",
            schema=old_schema,
            schema_hash="H1",
            graphql_sdl="old-sdl",
            fetched_at_monotonic=old_time,
            consecutive_failures=0,
        )
        mock_client._get.side_effect = [
            _make_response(json_body={"main": "H2"}),
            _make_response(text="new-sdl"),
        ]
        mock_client.schema.fetch.return_value = new_schema

        sdl = await get_cached_graphql_sdl(mock_ctx)

        assert sdl == "new-sdl"


# ---------------------------------------------------------------------------
# Middleware schema-URI bypass
# ---------------------------------------------------------------------------


class TestSchemaAwareCachingMiddleware:
    @pytest.mark.anyio
    async def test_schema_uri_bypasses_cache(self) -> None:
        from fastmcp.server.middleware.caching import (
            CallToolSettings,
            ListPromptsSettings,
            ListResourcesSettings,
            ListToolsSettings,
            ReadResourceSettings,
        )

        from infrahub_mcp.middleware import _SchemaAwareResponseCachingMiddleware

        mw = _SchemaAwareResponseCachingMiddleware(
            list_tools_settings=ListToolsSettings(ttl=300),
            list_resources_settings=ListResourcesSettings(ttl=300),
            list_prompts_settings=ListPromptsSettings(ttl=300),
            read_resource_settings=ReadResourceSettings(ttl=300),
            call_tool_settings=CallToolSettings(ttl=300, excluded_tools=["get_schema"]),
        )

        mock_msg = MagicMock()
        mock_msg.uri = "infrahub://schema"
        mock_ctx = MagicMock()
        mock_ctx.message = mock_msg

        call_next_count = 0

        async def call_next(_ctx: Any) -> str:
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
        from fastmcp.server.middleware.caching import (
            CallToolSettings,
            ListPromptsSettings,
            ListResourcesSettings,
            ListToolsSettings,
            ReadResourceSettings,
        )

        from infrahub_mcp.middleware import _SchemaAwareResponseCachingMiddleware

        mw = _SchemaAwareResponseCachingMiddleware(
            list_tools_settings=ListToolsSettings(ttl=300),
            list_resources_settings=ListResourcesSettings(ttl=300),
            list_prompts_settings=ListPromptsSettings(ttl=300),
            read_resource_settings=ReadResourceSettings(ttl=300),
            call_tool_settings=CallToolSettings(ttl=300, excluded_tools=["get_schema"]),
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
