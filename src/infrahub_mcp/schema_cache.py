"""Hash-validated schema cache for the Infrahub MCP server.

In passthrough auth modes (``token-passthrough`` / ``basic-passthrough``)
``get_client(ctx)`` builds a fresh ``InfrahubClient`` per request, which
discards the SDK's per-client schema cache. Without an extra layer, every
schema-touching request would refetch ``/api/schema``.

This module provides a process-wide cache stored on ``AppContext`` keyed
by branch name. The cache is correctness-preserving via the upstream
schema hash returned from ``GET /api/schema/summary``:

- A short skip-window (``schema_cache_ttl``) lets bursts of requests
  serve from cache without any upstream call.
- Past the skip-window, the helper fetches the cheap ``/summary`` payload
  and compares ``main`` against the cached ``BranchSchema.hash``. Match
  extends the cache; differ triggers a full refetch.
- A successful fetch also primes the fresh client's per-client cache via
  ``client.schema.set_cache(...)`` so subsequent ``client.schema.*``
  calls inside the same request hit the SDK cache.
- Transient revalidation/refetch failures serve stale + emit a WARN log;
  configurable circuit-break thresholds bound how long stale data may be
  served before reads fail closed.

See ``specs/20260504-203256-schema-cache/`` for the full design.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import httpx
from fastmcp.exceptions import ToolError
from infrahub_sdk.exceptions import SchemaNotFoundError

from infrahub_mcp.utils import AppContext, get_client, get_default_branch

if TYPE_CHECKING:
    from typing import Any

    from fastmcp import Context
    from infrahub_sdk.client import InfrahubClient
    from infrahub_sdk.schema import BranchSchema

logger = logging.getLogger("infrahub_mcp.schema_cache")


@dataclass(frozen=True, slots=True)
class CachedSchemaEntry:
    """Immutable per-branch cache snapshot.

    Storing each cache value as an immutable dataclass means readers can
    pull the entry from the dict without holding a lock — under the GIL
    a single dict assignment is atomic, so a reader either sees the old
    entry or the new one, never a torn intermediate.
    """

    branch: str
    schema: BranchSchema
    schema_hash: str
    graphql_sdl: str
    fetched_at_monotonic: float
    consecutive_failures: int = 0


class _BranchGoneError(Exception):
    """Raised by ``_fetch_summary_hash`` when ``/summary`` returns 404 for a branch."""


def _now() -> float:
    return time.monotonic()


def _is_circuit_broken(
    entry: CachedSchemaEntry,
    *,
    max_consecutive_failures: int,
    max_staleness_seconds: int,
    now: float,
) -> bool:
    if max_consecutive_failures and entry.consecutive_failures >= max_consecutive_failures:
        return True
    return bool(max_staleness_seconds and (now - entry.fetched_at_monotonic) >= max_staleness_seconds)


def _is_within_skip_window(entry: CachedSchemaEntry, *, skip_window_seconds: int, now: float) -> bool:
    if skip_window_seconds <= 0:
        return False
    return (now - entry.fetched_at_monotonic) < skip_window_seconds


def _get_app_ctx(ctx: Context) -> AppContext:
    if ctx.request_context is None:
        msg = "request_context must not be None"
        raise RuntimeError(msg)
    return ctx.request_context.lifespan_context


async def _resolve_branch(ctx: Context, branch: str | None) -> str:
    """Return the resolved branch name, mapping ``None``/empty to the default branch."""
    if branch:
        return branch
    return await get_default_branch(ctx)


async def _fetch_summary_hash(client: InfrahubClient, branch: str) -> str:
    """Return the current ``main`` schema hash from ``GET /api/schema/summary``.

    Raises :class:`_BranchGoneError` on HTTP 404 so the caller can evict
    the cache entry. Other HTTP errors propagate.

    The Infrahub SDK does not yet expose a public wrapper for this
    endpoint; the call uses ``client._get`` mirroring the existing
    pattern in ``resources/schema.py`` for the GraphQL SDL fetch.
    TODO: swap for ``client.schema.summary()`` once the upstream SDK PR
    lands.
    """
    url = f"{client.address}/api/schema/summary?branch={branch}"
    response = await client._get(url=url)  # noqa: SLF001  # pylint: disable=protected-access
    if response.status_code == httpx.codes.NOT_FOUND:
        raise _BranchGoneError(branch)
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    main_hash = payload.get("main")
    if not main_hash:
        msg = f"/api/schema/summary did not return 'main' hash for branch {branch!r}"
        raise RuntimeError(msg)
    return str(main_hash)


async def _fetch_graphql_sdl(client: InfrahubClient) -> str:
    """Fetch the raw GraphQL SDL via ``GET /schema.graphql``.

    Mirrors the existing call in ``resources/schema.py``.
    """
    response = await client._get(url=f"{client.address}/schema.graphql")  # noqa: SLF001  # pylint: disable=protected-access
    response.raise_for_status()
    return response.text


async def _full_fetch(
    client: InfrahubClient,
    branch: str,
) -> tuple[BranchSchema, str]:
    """Fetch the full BranchSchema and the GraphQL SDL for a branch.

    Returns a ``(branch_schema, graphql_sdl)`` tuple. The two fetches
    happen sequentially — they are different endpoints and a small
    sequence keeps error attribution clear.

    The SDK's public ``client.schema.fetch()`` returns only the kinds
    dict (``dict[str, MainSchemaTypes]``), not the ``BranchSchema``
    object that carries the schema hash we need for hash-validated
    revalidation. ``client.schema._fetch()`` is the inner method that
    returns the full ``BranchSchema`` — same protected-member precedent
    as the ``client._get`` calls used elsewhere in this module.
    TODO: swap for a public SDK accessor when one lands.
    """
    branch_schema: BranchSchema = await client.schema._fetch(branch=branch)  # noqa: SLF001  # pylint: disable=protected-access
    graphql_sdl = await _fetch_graphql_sdl(client)
    return branch_schema, graphql_sdl


def _record_circuit_break(metrics: Any, branch: str, threshold: str, age: float) -> None:
    metrics.record_schema_cache_event("circuit_break")
    logger.error(
        "schema_cache_circuit_break branch=%s threshold=%s last_success_age_seconds=%.1f",
        branch,
        threshold,
        age,
    )


async def _cold_fetch_under_lock(
    *,
    app_ctx: AppContext,
    client: InfrahubClient,
    branch: str,
) -> CachedSchemaEntry:
    """Cold-fetch path: no entry exists for *branch*. Caller holds the lock."""
    branch_schema, graphql_sdl = await _full_fetch(client, branch)
    entry = CachedSchemaEntry(
        branch=branch,
        schema=branch_schema,
        schema_hash=branch_schema.hash or "",
        graphql_sdl=graphql_sdl,
        fetched_at_monotonic=_now(),
        consecutive_failures=0,
    )
    app_ctx.schema_cache[branch] = entry
    return entry


async def _revalidate_under_lock(
    *,
    app_ctx: AppContext,
    client: InfrahubClient,
    entry: CachedSchemaEntry,
    metrics: Any,
) -> CachedSchemaEntry:
    """Revalidate an existing cache entry. Caller holds the lock.

    On hash match: refresh the entry's ``fetched_at_monotonic`` and zero
    its ``consecutive_failures`` (cache is current).

    On hash differ: full refetch and replace the entry.

    On 404 from ``/summary``: evict the entry and re-raise the original
    error path (cold-fetch on next call).

    On any other failure (transient): preserve the existing entry's
    schema/hash/SDL but increment ``consecutive_failures`` and update
    nothing else. Emit WARN log. Return the (failure-incremented) entry.
    """
    branch = entry.branch
    try:
        upstream_hash = await _fetch_summary_hash(client, branch)
    except _BranchGoneError:
        del app_ctx.schema_cache[branch]
        logger.warning("schema_cache_branch_gone branch=%s", branch)
        raise
    except Exception as exc:  # noqa: BLE001
        new_entry = replace(entry, consecutive_failures=entry.consecutive_failures + 1)
        app_ctx.schema_cache[branch] = new_entry
        if metrics is not None:
            metrics.record_schema_cache_event("revalidate_failure")
        logger.warning(
            "schema_cache_revalidate_failure branch=%s exception=%r",
            branch,
            exc,
        )
        return new_entry

    if upstream_hash == entry.schema_hash:
        refreshed = replace(entry, fetched_at_monotonic=_now(), consecutive_failures=0)
        app_ctx.schema_cache[branch] = refreshed
        if metrics is not None:
            metrics.record_schema_cache_event("hash_match")
        return refreshed

    # Hash differs — full refetch.
    try:
        branch_schema, graphql_sdl = await _full_fetch(client, branch)
    except Exception as exc:  # noqa: BLE001
        new_entry = replace(entry, consecutive_failures=entry.consecutive_failures + 1)
        app_ctx.schema_cache[branch] = new_entry
        if metrics is not None:
            metrics.record_schema_cache_event("revalidate_failure")
        logger.warning(
            "schema_cache_refetch_failure branch=%s exception=%r",
            branch,
            exc,
        )
        return new_entry

    refreshed = CachedSchemaEntry(
        branch=branch,
        schema=branch_schema,
        schema_hash=branch_schema.hash or upstream_hash,
        graphql_sdl=graphql_sdl,
        fetched_at_monotonic=_now(),
        consecutive_failures=0,
    )
    app_ctx.schema_cache[branch] = refreshed
    if metrics is not None:
        metrics.record_schema_cache_event("hash_diff")
    return refreshed


def _install_into_client(client: InfrahubClient, entry: CachedSchemaEntry) -> None:
    """Pre-populate the fresh client's per-client SDK cache for *entry*'s branch.

    After this call, ``client.schema.all(branch=entry.branch)`` and
    ``client.schema.get(kind=..., branch=entry.branch)`` are served from
    the SDK's in-memory cache, transparently to existing call sites.
    """
    client.schema.set_cache(schema=entry.schema, branch=entry.branch)


def _check_circuit_break(  # noqa: PLR0913
    entry: CachedSchemaEntry,
    *,
    max_failures: int,
    max_staleness: int,
    metrics: Any,
    branch: str,
    now: float,
    msg_suffix: str = "circuit-break threshold reached. The Infrahub server may be unreachable; check server health and try again.",
) -> None:
    """Raise ``ToolError`` if *entry* has crossed a circuit-break threshold."""
    if not _is_circuit_broken(
        entry,
        max_consecutive_failures=max_failures,
        max_staleness_seconds=max_staleness,
        now=now,
    ):
        return
    threshold = (
        "consecutive_failures" if max_failures and entry.consecutive_failures >= max_failures else "max_staleness"
    )
    _record_circuit_break(metrics, branch, threshold, now - entry.fetched_at_monotonic)
    msg = f"Schema temporarily unavailable for branch {branch!r}: {msg_suffix}"
    raise ToolError(msg)


def _try_serve_from_cache(
    *,
    app_ctx: AppContext,
    client: InfrahubClient,
    resolved_branch: str,
    force_revalidate: bool,
    metrics: Any,
) -> CachedSchemaEntry | None:
    """Hot-path attempt: return a current entry without acquiring the cache lock.

    Returns the entry if it is within the skip-window, or ``None`` if the
    caller must take the lock (cold cache or past skip-window). Raises
    ``ToolError`` if the entry has crossed a circuit-break threshold.
    """
    entry = app_ctx.schema_cache.get(resolved_branch)
    if entry is None or force_revalidate:
        return None

    config = app_ctx.config
    now = _now()
    _check_circuit_break(
        entry,
        max_failures=config.schema_cache_max_consecutive_failures,
        max_staleness=config.schema_cache_max_staleness_seconds,
        metrics=metrics,
        branch=resolved_branch,
        now=now,
    )
    if _is_within_skip_window(entry, skip_window_seconds=config.schema_cache_ttl, now=now):
        if metrics is not None:
            metrics.record_schema_cache_event("hit")
        _install_into_client(client, entry)
        return entry
    return None


async def _ensure_entry(
    *,
    ctx: Context,
    branch: str | None,
    force_revalidate: bool,
) -> CachedSchemaEntry:
    """Core cache flow: returns a current entry for *branch*, or raises.

    Honors skip-window TTL, hash-validated revalidation, single-flight
    via the cache lock, circuit-break thresholds, and 404-evicts.
    """
    app_ctx = _get_app_ctx(ctx)
    resolved_branch = await _resolve_branch(ctx, branch)
    config = app_ctx.config
    metrics = _get_metrics()
    client = get_client(ctx)

    hot_entry = _try_serve_from_cache(
        app_ctx=app_ctx,
        client=client,
        resolved_branch=resolved_branch,
        force_revalidate=force_revalidate,
        metrics=metrics,
    )
    if hot_entry is not None:
        return hot_entry

    async with app_ctx._schema_cache_lock:  # noqa: SLF001
        # Re-read after acquiring lock — another waiter may have populated.
        hot_entry = _try_serve_from_cache(
            app_ctx=app_ctx,
            client=client,
            resolved_branch=resolved_branch,
            force_revalidate=force_revalidate,
            metrics=metrics,
        )
        if hot_entry is not None:
            return hot_entry

        entry = app_ctx.schema_cache.get(resolved_branch)
        if entry is None:
            if metrics is not None:
                metrics.record_schema_cache_event("miss")
            new_entry = await _cold_fetch_under_lock(
                app_ctx=app_ctx,
                client=client,
                branch=resolved_branch,
            )
        else:
            new_entry = await _revalidate_under_lock(
                app_ctx=app_ctx,
                client=client,
                entry=entry,
                metrics=metrics,
            )

    _check_circuit_break(
        new_entry,
        max_failures=config.schema_cache_max_consecutive_failures,
        max_staleness=config.schema_cache_max_staleness_seconds,
        metrics=metrics,
        branch=resolved_branch,
        now=_now(),
        msg_suffix="circuit-break threshold reached after revalidation failure.",
    )
    _install_into_client(client, new_entry)
    return new_entry


def _get_metrics() -> Any:
    """Return the metrics middleware instance, or None if not configured.

    Imported lazily because ``middleware.py`` is a heavy module that imports
    fastmcp middleware classes; loading it at top of ``schema_cache.py`` would
    pull in those dependencies during ``utils.py`` import (utils → schema_cache
    via the AppContext field default).
    """
    from infrahub_mcp.middleware import get_metrics  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

    return get_metrics()


async def get_cached_branch_schema(ctx: Context, branch: str | None = None) -> BranchSchema:
    """Return the cached ``BranchSchema`` for *branch* (default branch when None).

    Side effect: the per-request fresh ``InfrahubClient`` returned by
    :func:`infrahub_mcp.utils.get_client` has its per-client SDK schema
    cache populated for *branch* via ``client.schema.set_cache(...)``,
    so subsequent ``client.schema.all(branch=...)`` and
    ``client.schema.get(kind=..., branch=...)`` calls within this
    request are served from the SDK's in-memory cache.

    When ``schema_cache_enabled`` is False, performs a fresh fetch on
    every call (pre-feature baseline).
    """
    app_ctx = _get_app_ctx(ctx)
    if not app_ctx.config.schema_cache_enabled:
        client = get_client(ctx)
        resolved_branch = await _resolve_branch(ctx, branch)
        return await client.schema._fetch(branch=resolved_branch)  # noqa: SLF001  # pylint: disable=protected-access

    entry = await _ensure_entry(ctx=ctx, branch=branch, force_revalidate=False)
    return entry.schema


async def get_cached_graphql_sdl(ctx: Context, branch: str | None = None) -> str:
    """Return the cached GraphQL SDL for *branch* (default branch when None).

    Shares the same hash gate as :func:`get_cached_branch_schema`; the
    SDL is invalidated together with the structured schema. When
    ``schema_cache_enabled`` is False, fetches fresh every call.
    """
    app_ctx = _get_app_ctx(ctx)
    if not app_ctx.config.schema_cache_enabled:
        client = get_client(ctx)
        return await _fetch_graphql_sdl(client)

    entry = await _ensure_entry(ctx=ctx, branch=branch, force_revalidate=False)
    return entry.graphql_sdl


async def get_cached_kind(ctx: Context, kind: str, branch: str | None = None) -> Any:
    """Return the schema for *kind* on *branch* with lazy refresh on miss.

    If the kind is missing from the cached BranchSchema, force one
    revalidation (bypassing the skip-window) before propagating
    :class:`SchemaNotFoundError`. This catches the case where the kind
    was added upstream after the cache was populated but before the
    skip-window elapsed.
    """
    schema = await get_cached_branch_schema(ctx, branch=branch)
    nodes = schema.nodes
    if kind in nodes:
        return nodes[kind]

    # Lazy revalidation: kind absent, the cache may be stale.
    app_ctx = _get_app_ctx(ctx)
    if not app_ctx.config.schema_cache_enabled:
        # Caching off — defer to the SDK's regular error path.
        client = get_client(ctx)
        resolved_branch = await _resolve_branch(ctx, branch)
        return await client.schema.get(kind=kind, branch=resolved_branch)

    entry = await _ensure_entry(ctx=ctx, branch=branch, force_revalidate=True)
    if kind in entry.schema.nodes:
        return entry.schema.nodes[kind]
    raise SchemaNotFoundError(identifier=kind)
