"""Hash-validated schema cache for the Infrahub MCP server.

In the passthrough auth modes ``get_client`` builds a new ``InfrahubClient``
for every request, so the SDK's per-client schema cache never outlives a
request. This module keeps one ``BranchSchema`` per branch on ``AppContext``
and checks it against the schema hash from ``GET /api/schema/summary``:

- Inside the skip-window (``schema_cache_ttl``) an entry is served without
  an upstream call. Past it, a ``/summary`` probe confirms the hash or
  triggers a full refetch.
- A transient failure serves the stale entry until a circuit-break threshold
  is reached. After a failure, upstream attempts are throttled per branch.
- In the passthrough modes a caller is served only after Infrahub accepted
  its own credential during the same request. A rejected credential fails
  that caller alone and leaves the cache untouched.
- The cache holds at most ``schema_cache_max_branches`` branches and evicts
  the least recently used one.
- The GraphQL SDL is fetched only when ``infrahub://graphql-schema`` is read.

Every read primes the SDK cache of the client it was given, so that client's
later ``client.schema`` calls in the request need no fetch.

The design and the reason for each rule are in
``dev/adr/0010-hash-validated-schema-cache.md``.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING
from urllib.parse import urlencode

import httpx
from fastmcp.exceptions import ToolError
from infrahub_sdk.exceptions import AuthenticationError, BranchNotFoundError, SchemaNotFoundError

from infrahub_mcp.constants import AUTH_MODE_BASIC_PASSTHROUGH, AUTH_MODE_TOKEN_PASSTHROUGH
from infrahub_mcp.utils import AppContext, get_app_ctx, get_default_branch, resolve_client

if TYPE_CHECKING:
    from contextlib import AbstractAsyncContextManager
    from typing import Any, NoReturn

    from fastmcp import Context
    from infrahub_sdk.client import InfrahubClient
    from infrahub_sdk.schema import BranchSchema, MainSchemaTypesAPI

    from infrahub_mcp.config import ServerConfig

logger = logging.getLogger("infrahub_mcp.schema_cache")


@dataclass(frozen=True, slots=True)
class CachedSchemaEntry:
    """Immutable cache value for one branch.

    Entries are frozen, so readers take one from the dict without a lock: a dict
    assignment is atomic, and a reader sees either the old entry or the new one.
    An entry is removed when a probe reports the branch gone or when
    :func:`_evict_lru` reclaims it. The next read of that branch fetches it again.
    """

    branch: str
    schema: BranchSchema
    schema_hash: str
    """The ``main`` hash that ``/summary`` probes are compared against.

    ``""`` when ``/api/schema`` returned no hash: the first probe then mismatches
    and the refetch stores the probe's hash (see :func:`_cold_fetch_under_lock`).
    """
    graphql_sdl: str | None
    """GraphQL SDL of the branch, or ``None`` until :func:`_fill_graphql_sdl` fetches it."""
    fetched_at_monotonic: float
    """Monotonic time of the last successful fetch or revalidation. Drives the skip-window."""
    consecutive_failures: int = 0
    last_attempt_monotonic: float = 0.0
    """Monotonic time of the last upstream attempt, successful or not.

    With ``consecutive_failures`` it throttles probes after a failure. On its own
    it debounces forced revalidations (:data:`_FORCED_REVALIDATE_DEBOUNCE_SECONDS`).
    """
    failing_since_monotonic: float | None = None
    """Monotonic time of the first failed probe of the current failure streak, or ``None``.

    ``schema_cache_max_staleness_seconds`` is measured from here rather than from
    the last success, so time when nobody read the branch does not count.
    """
    circuit_break_recorded: bool = False
    """Whether the ``circuit_break`` metric was already recorded for the current failure streak."""
    graphql_sdl_last_failure_monotonic: float | None = None
    """Monotonic time of the last failed SDL fetch, or ``None``.

    For ``min(schema_cache_ttl, 30 s)`` after it, SDL reads fail without an
    upstream call. A refetch builds a new entry without it.
    """


# Status codes ``/api/schema/summary`` answers for a branch that no longer
# exists. Infrahub raises ``BranchNotFoundError`` (``HTTP_CODE = 400``) from
# the endpoint's branch dependency, and the SDK maps 400 from ``/api/schema``
# to ``BranchNotFoundError`` too. 404 is not included: Infrahub uses it for a
# missing resource, so a 404 here means the endpoint itself is unreachable
# (a proxy that does not forward it, an older server). Treating that as
# "branch gone" would drop every entry, ``main`` included, on each probe.
_BRANCH_GONE_STATUS_CODES: frozenset[int] = frozenset({httpx.codes.BAD_REQUEST})


class _BranchGoneError(Exception):
    """Raised by ``_fetch_summary_hash`` when ``/summary`` answers 400 for the branch."""


# Status codes that mean Infrahub rejected the *caller's* credential rather
# than failing the request: 401 (missing or invalid token) and 403 (token
# lacks the permission). The same pair ``InfrahubClient.execute_graphql``
# maps to ``AuthenticationError``.
_AUTH_STATUS_CODES: frozenset[int] = frozenset({httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN})


def _is_auth_error(exc: BaseException) -> bool:
    """Return True when *exc* means Infrahub rejected the caller's credential (HTTP 401 or 403).

    The SDK (``infrahub_sdk`` 1.22.2) reports this in two forms:

    - ``httpx.HTTPStatusError``, from ``raise_for_status()``. ``client._get``
      does not raise on status, so this module's own requests call it, as does
      the SDK's ``/api/schema`` parser. ``login()`` raises it too when it
      refuses ``basic-passthrough`` credentials.
    - ``AuthenticationError``, from ``login(refresh=True)``.

    In the passthrough modes the credential is the caller's, so neither form
    counts as an upstream failure.
    """
    if isinstance(exc, AuthenticationError):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in _AUTH_STATUS_CODES


def _raise_auth_error(exc: Exception, *, branch: str) -> NoReturn:
    """Raise *exc* to the caller as ``AuthenticationError`` and leave the cache unchanged.

    ``InfrahubConnectionMiddleware`` then reports it as it reports a rejected
    GraphQL query. The log line holds the status and URL, never the credential.
    """
    status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
    logger.warning("schema_cache_auth_error branch=%s status=%s exception=%r", branch, status, exc)
    if isinstance(exc, AuthenticationError):
        raise exc
    msg = f"Infrahub answered HTTP {status} for the schema of branch {branch!r}"
    raise AuthenticationError(msg) from exc


def _now() -> float:
    return time.monotonic()


def _is_circuit_broken(
    entry: CachedSchemaEntry,
    *,
    max_consecutive_failures: int,
    max_staleness_seconds: int,
    now: float,
) -> bool:
    """Return True when *entry* has crossed either circuit-break threshold.

    The staleness threshold is measured from ``failing_since_monotonic``. A
    threshold of 0 turns that check off.
    """
    if max_consecutive_failures and entry.consecutive_failures >= max_consecutive_failures:
        return True
    if not max_staleness_seconds or entry.failing_since_monotonic is None:
        return False
    return (now - entry.failing_since_monotonic) >= max_staleness_seconds


def _within_window(since_monotonic: float, *, window_seconds: float, now: float) -> bool:
    """Return True when *since_monotonic* is less than *window_seconds* ago. A window of 0 or less is off."""
    if window_seconds <= 0:
        return False
    return (now - since_monotonic) < window_seconds


def _is_within_skip_window(entry: CachedSchemaEntry, *, skip_window_seconds: int, now: float) -> bool:
    return _within_window(entry.fetched_at_monotonic, window_seconds=skip_window_seconds, now=now)


def _is_retry_throttled(last_attempt_monotonic: float, *, throttle_seconds: int, now: float) -> bool:
    """Return True when the last attempt is less than *throttle_seconds* ago. 0 turns the throttle off."""
    return _within_window(last_attempt_monotonic, window_seconds=throttle_seconds, now=now)


_MAX_RECOVERY_PROBE_SECONDS = 30
"""Upper bound, in seconds, on the probe-throttle window that follows a failed attempt.

The window is ``min(schema_cache_ttl, 30)``, so a long TTL does not delay
recovery once Infrahub is reachable again. ``schema_cache_ttl = 0`` turns the
throttle off.
"""


def _recovery_probe_seconds(config: ServerConfig) -> int:
    """Return the probe-throttle window applied after a failed upstream attempt."""
    return min(config.schema_cache_ttl, _MAX_RECOVERY_PROBE_SECONDS)


_FORCED_REVALIDATE_DEBOUNCE_SECONDS = 2
"""Debounce, in seconds, on the revalidations that a missing kind forces.

A tool call that looks up several unknown kinds, such as relationship peers,
costs one ``/summary`` probe instead of one per kind. Any upstream attempt
starts the debounce. It does not depend on ``schema_cache_ttl``.
"""


def _is_forced_probe_debounced(entry: CachedSchemaEntry, *, now: float) -> bool:
    """Return True when any upstream attempt for *entry* landed inside the forced-revalidation debounce."""
    return _within_window(entry.last_attempt_monotonic, window_seconds=_FORCED_REVALIDATE_DEBOUNCE_SECONDS, now=now)


def _branch_lock(app_ctx: AppContext, branch: str) -> AbstractAsyncContextManager[None]:
    """Hold *branch*'s structured-schema lock for the block.

    Makes the full fetch of a branch single-flight. The SDL fetch uses a separate
    lock, so a slow ``/schema.graphql`` does not delay structured-schema reads.
    """
    return app_ctx._schema_cache_locks.hold(branch)  # noqa: SLF001


def _touch(app_ctx: AppContext, branch: str) -> None:
    """Mark *branch* as the most recently used entry, if it is still cached."""
    if branch in app_ctx.schema_cache:
        app_ctx.schema_cache.move_to_end(branch)


def _evict_lru(app_ctx: AppContext, *, keep: str | None = None) -> None:
    """Evict least recently used entries until the cache is within ``schema_cache_max_branches``.

    Branch names are caller input, so without a bound the cache would grow with
    every session branch. A branch whose lock is held or awaited is never
    evicted, nor is *keep*. If nothing else can go, the cache stays over its
    bound until the next store.
    """
    cap = app_ctx.config.schema_cache_max_branches
    if not cap:
        return
    locks = app_ctx._schema_cache_locks  # noqa: SLF001
    while len(app_ctx.schema_cache) > cap:
        victim = next(
            (branch for branch in app_ctx.schema_cache if branch != keep and not locks.in_use(branch)),
            None,
        )
        if victim is None:
            return
        _drop_entry(app_ctx, victim)
        logger.debug("schema_cache_evicted branch=%s max_branches=%d", victim, cap)


def _drop_entry(app_ctx: AppContext, branch: str) -> None:
    """Remove *branch* from the cache and from the shared lifespan client's SDK cache.

    Uses ``pop`` because a lock-free probe can remove the same entry at the same
    time. Without dropping the lifespan client's copy, eviction would free no
    memory in the shared-client modes.
    """
    app_ctx.schema_cache.pop(branch, None)
    if app_ctx.client is not None:
        app_ctx.client.schema.cache.pop(branch, None)


def _sweep_cold_failures(app_ctx: AppContext, *, now: float) -> None:
    """Drop cold-failure markers older than the probe-throttle window.

    An expired marker has no effect, and branch names are caller input, so the
    map is swept each time a marker is added.
    """
    window = _recovery_probe_seconds(app_ctx.config)
    expired = [
        branch
        for branch, failed_at in app_ctx.schema_cache_cold_failures.items()
        if not _is_retry_throttled(failed_at, throttle_seconds=window, now=now)
    ]
    for branch in expired:
        del app_ctx.schema_cache_cold_failures[branch]


def _store_entry(app_ctx: AppContext, entry: CachedSchemaEntry) -> None:
    """Store *entry*, mark it most recently used, then enforce the cache bound.

    The only write path into ``AppContext.schema_cache``.
    """
    app_ctx.schema_cache[entry.branch] = entry
    app_ctx.schema_cache.move_to_end(entry.branch)
    _evict_lru(app_ctx, keep=entry.branch)


async def _resolve_branch(ctx: Context, branch: str | None) -> str:
    """Return the resolved branch name, mapping ``None``/empty to the default branch."""
    if branch:
        return branch
    return await get_default_branch(ctx)


async def _branch_get(client: InfrahubClient, path: str, branch: str) -> httpx.Response:
    """``GET`` *path* for *branch* and return the response, without status handling.

    The branch is URL-encoded: Infrahub allows ``#`` and ``&`` in branch names,
    and an unencoded query string would return the default branch's data.
    """
    url = f"{client.address}{path}?{urlencode([('branch', branch)])}"
    return await client._get(url=url)  # noqa: SLF001  # pylint: disable=protected-access


async def _fetch_summary_hash(client: InfrahubClient, branch: str) -> str:
    """Return the ``main`` schema hash from ``GET /api/schema/summary``.

    Raises :class:`_BranchGoneError` on HTTP 400. The SDK has no public call for
    this endpoint. TODO: use ``client.schema.summary()`` once the SDK adds it.
    """
    response = await _branch_get(client, "/api/schema/summary", branch)
    if response.status_code in _BRANCH_GONE_STATUS_CODES:
        raise _BranchGoneError(branch)
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    main_hash = payload.get("main")
    if not main_hash:
        msg = f"/api/schema/summary did not return 'main' hash for branch {branch!r}"
        raise RuntimeError(msg)
    return str(main_hash)


async def _fetch_graphql_sdl(client: InfrahubClient, branch: str) -> str:
    """Return the GraphQL SDL of *branch* from ``GET /schema.graphql``.

    Does not use ``client.schema.get_graphql_schema``: it does not URL-encode the
    branch, and it turns every non-200 answer into a ``ValueError``, which hides
    a 401 or 403 from :func:`_is_auth_error`.
    """
    response = await _branch_get(client, "/schema.graphql", branch)
    response.raise_for_status()
    return response.text


async def _full_fetch(client: InfrahubClient, branch: str) -> BranchSchema:
    """Fetch the full ``BranchSchema`` of *branch*, without the GraphQL SDL.

    Uses the private ``client.schema._fetch`` because the public ``fetch()``
    drops the schema hash. TODO: use a public SDK call when one exists.
    """
    branch_schema: BranchSchema = await client.schema._fetch(branch=branch)  # noqa: SLF001  # pylint: disable=protected-access
    return branch_schema


def _record_circuit_break(metrics: Any, branch: str, threshold: str, failing_for_seconds: float) -> None:
    """Record that a failure streak tripped the breaker: once per streak, not once per rejected read."""
    if metrics is not None:
        metrics.record_schema_cache_event("circuit_break")
    logger.error(
        "schema_cache_circuit_break branch=%s threshold=%s failing_for_seconds=%.1f",
        branch,
        threshold,
        failing_for_seconds,
    )


def _breach_threshold_name(entry: CachedSchemaEntry, *, max_failures: int) -> str:
    return "consecutive_failures" if max_failures and entry.consecutive_failures >= max_failures else "max_staleness"


def _note_failure(
    *,
    app_ctx: AppContext,
    entry: CachedSchemaEntry,
    metrics: Any,
    now: float,
) -> CachedSchemaEntry:
    """Store *entry* with one more failure, and record the breaker trip if this failure caused it.

    Starts a failure streak when none is in progress. A rejected credential
    never reaches this function.
    """
    config = app_ctx.config
    max_failures = config.schema_cache_max_consecutive_failures
    max_staleness = config.schema_cache_max_staleness_seconds

    failing_since = now if entry.failing_since_monotonic is None else entry.failing_since_monotonic
    new_entry = replace(
        entry,
        consecutive_failures=entry.consecutive_failures + 1,
        last_attempt_monotonic=now,
        failing_since_monotonic=failing_since,
    )
    if metrics is not None:
        metrics.record_schema_cache_event("revalidate_failure")

    broken = _is_circuit_broken(
        new_entry,
        max_consecutive_failures=max_failures,
        max_staleness_seconds=max_staleness,
        now=now,
    )
    if broken and not new_entry.circuit_break_recorded:
        new_entry = replace(new_entry, circuit_break_recorded=True)
        _record_circuit_break(
            metrics,
            entry.branch,
            _breach_threshold_name(new_entry, max_failures=max_failures),
            now - failing_since,
        )
    _store_entry(app_ctx, new_entry)
    return new_entry


def _entry_after_await(app_ctx: AppContext, entry: CachedSchemaEntry) -> CachedSchemaEntry:
    """Return the current entry of *entry*'s branch, for a lock holder updating it after an ``await``.

    A lock-free probe may have refreshed or dropped the entry in the meantime.
    A missing entry means a probe found the branch gone, so this raises
    ``BranchNotFoundError``.
    """
    current = app_ctx.schema_cache.get(entry.branch)
    if current is None:
        logger.warning("schema_cache_branch_gone branch=%s", entry.branch)
        raise BranchNotFoundError(identifier=entry.branch)
    return current


def _store_hash_match(app_ctx: AppContext, entry: CachedSchemaEntry, metrics: Any) -> CachedSchemaEntry:
    """Store *entry* refreshed after a ``/summary`` probe matched its hash, and return the stored copy.

    The cache is current: the skip-window restarts and any failure streak ends.
    """
    now = _now()
    refreshed = replace(
        entry,
        fetched_at_monotonic=now,
        consecutive_failures=0,
        last_attempt_monotonic=now,
        failing_since_monotonic=None,
        circuit_break_recorded=False,
    )
    _store_entry(app_ctx, refreshed)
    if metrics is not None:
        metrics.record_schema_cache_event("hash_match")
    return refreshed


def _note_transient_failure(
    exc: Exception,
    *,
    app_ctx: AppContext,
    entry: CachedSchemaEntry,
    metrics: Any,
    event: str,
) -> CachedSchemaEntry:
    """Handle an upstream failure on *entry*. The caller holds the branch lock.

    A rejected credential is raised to the caller. Any other failure is counted
    on the current entry and logged as *event*, and the updated entry is
    returned so the caller can serve it stale.
    """
    if _is_auth_error(exc):
        _raise_auth_error(exc, branch=entry.branch)
    entry = _entry_after_await(app_ctx, entry)
    new_entry = _note_failure(app_ctx=app_ctx, entry=entry, metrics=metrics, now=_now())
    logger.warning(
        "%s branch=%s exception=%r",
        event,
        entry.branch,
        exc,
    )
    return new_entry


async def _cold_fetch_under_lock(
    *,
    app_ctx: AppContext,
    client: InfrahubClient,
    branch: str,
) -> CachedSchemaEntry:
    """Fetch and store *branch*, which has no entry. The caller holds the branch lock.

    A failure other than ``BranchNotFoundError`` or a rejected credential is
    recorded in ``AppContext.schema_cache_cold_failures`` before it is raised, so
    reads inside the probe-throttle window fail fast.

    When ``/api/schema`` returns no hash, the entry stores ``""``. A hash fetched
    from ``/summary`` after the content could be newer than the content and hide
    a change. Instead, the first probe mismatches ``""`` and the refetch stores
    the probe's hash.
    """
    try:
        branch_schema = await _full_fetch(client, branch)
    except BranchNotFoundError:
        raise
    except Exception as exc:
        if _is_auth_error(exc):
            _raise_auth_error(exc, branch=branch)
        failed_at = _now()
        _sweep_cold_failures(app_ctx, now=failed_at)
        app_ctx.schema_cache_cold_failures[branch] = failed_at
        logger.warning(
            "schema_cache_cold_fetch_failure branch=%s exception=%r",
            branch,
            exc,
        )
        raise
    now = _now()
    entry = CachedSchemaEntry(
        branch=branch,
        schema=branch_schema,
        # "" on purpose when the payload carried no hash. Probing /summary here
        # would run *after* the fetch and could pair a newer hash with older
        # content, hiding that change from every later probe. The first
        # past-window probe mismatches "" and the refetch stores its own
        # pre-fetch hash instead (see _revalidate_under_lock).
        schema_hash=branch_schema.hash or "",
        graphql_sdl=None,
        fetched_at_monotonic=now,
        consecutive_failures=0,
        last_attempt_monotonic=now,
    )
    _store_entry(app_ctx, entry)
    app_ctx.schema_cache_cold_failures.pop(branch, None)
    return entry


async def _revalidate_under_lock(
    *,
    app_ctx: AppContext,
    client: InfrahubClient,
    entry: CachedSchemaEntry,
    metrics: Any,
) -> CachedSchemaEntry:
    """Probe ``/summary`` for *entry*'s branch and update the entry. The caller holds the branch lock.

    - Hash matches: refresh the entry.
    - Hash differs: refetch the schema. The new entry has no SDL yet.
    - Branch gone (HTTP 400, or ``BranchNotFoundError`` on the refetch): drop
      the entry and raise ``BranchNotFoundError``.
    - Rejected credential: raise ``AuthenticationError`` and leave the entry
      unchanged.
    - Any other failure: count it and return the entry, to be served stale.
    """
    branch = entry.branch
    try:
        upstream_hash = await _fetch_summary_hash(client, branch)
    except _BranchGoneError as exc:
        # ``_drop_entry`` pops: an unvalidated passthrough caller probing outside
        # the lock may already have removed this entry while we awaited.
        _drop_entry(app_ctx, branch)
        logger.warning("schema_cache_branch_gone branch=%s", branch)
        raise BranchNotFoundError(identifier=branch) from exc
    except Exception as exc:  # noqa: BLE001
        return _note_transient_failure(
            exc, app_ctx=app_ctx, entry=entry, metrics=metrics, event="schema_cache_revalidate_failure"
        )

    if upstream_hash == entry.schema_hash:
        return _store_hash_match(app_ctx, _entry_after_await(app_ctx, entry), metrics)

    # Hash differs — full refetch.
    try:
        branch_schema = await _full_fetch(client, branch)
    except BranchNotFoundError:
        # Deleted between the probe and the refetch (the SDK maps the 400 from
        # /api/schema to this). That is the probe's branch-gone answer arriving
        # one call late, not a transient failure to serve stale through.
        _drop_entry(app_ctx, branch)
        logger.warning("schema_cache_branch_gone branch=%s", branch)
        raise
    except Exception as exc:  # noqa: BLE001
        return _note_transient_failure(
            exc, app_ctx=app_ctx, entry=entry, metrics=metrics, event="schema_cache_refetch_failure"
        )

    # Not stored if a lock-free probe found the branch gone while this refetch ran.
    _entry_after_await(app_ctx, entry)
    now = _now()
    refreshed = CachedSchemaEntry(
        branch=branch,
        schema=branch_schema,
        schema_hash=branch_schema.hash or upstream_hash,
        graphql_sdl=None,
        fetched_at_monotonic=now,
        consecutive_failures=0,
        last_attempt_monotonic=now,
    )
    _store_entry(app_ctx, refreshed)
    if metrics is not None:
        metrics.record_schema_cache_event("hash_diff")
    return refreshed


def _install_into_client(client: InfrahubClient, entry: CachedSchemaEntry) -> None:
    """Prime *client*'s SDK schema cache with *entry*, so its ``client.schema`` calls need no fetch."""
    client.schema.set_cache(schema=entry.schema, branch=entry.branch)


_PASSTHROUGH_AUTH_MODES = frozenset({AUTH_MODE_TOKEN_PASSTHROUGH, AUTH_MODE_BASIC_PASSTHROUGH})
"""Auth modes in which the credential behind a client is the caller's, not the server's."""


def _caller_is_validated(app_ctx: AppContext, client: InfrahubClient, branch: str) -> bool:
    """Return True when *client* may be served a cached entry for *branch* without an upstream call.

    Always True in the shared-credential modes. In the passthrough modes
    ``get_client`` only checks that a credential is present, so the client must
    already hold *branch* in its SDK cache. That happens only after an upstream
    call with its credential succeeded. Passthrough clients are built for each
    call, so nothing carries over from an earlier request.
    """
    if app_ctx.config.auth_mode not in _PASSTHROUGH_AUTH_MODES:
        return True
    return branch in client.schema.cache


_UNREACHABLE_HINT = "The Infrahub server may be unreachable; check server health and try again."
_CIRCUIT_BREAK_MSG = f"circuit-break threshold reached. {_UNREACHABLE_HINT}"


def _raise_schema_unavailable(branch: str, msg_suffix: str) -> NoReturn:
    msg = f"Schema temporarily unavailable for branch {branch!r}: {msg_suffix}"
    raise ToolError(msg)


def _raise_if_attempt_throttled(
    branch: str,
    failed_at: float | None,
    *,
    config: ServerConfig,
    now: float,
    what: str,
) -> None:
    """Raise ``ToolError`` if the attempt named *what* failed at *failed_at*, inside the probe-throttle window.

    The message gives the seconds left before the next upstream attempt.
    """
    if failed_at is None:
        return
    window = _recovery_probe_seconds(config)
    if not _is_retry_throttled(failed_at, throttle_seconds=window, now=now):
        return
    elapsed = now - failed_at
    retry_in = math.ceil(window - elapsed)
    _raise_schema_unavailable(
        branch,
        f"{what} failed {elapsed:.0f} s ago; the next upstream attempt is in {retry_in} s. {_UNREACHABLE_HINT}",
    )


def _raise_if_cold_fetch_throttled(app_ctx: AppContext, *, branch: str, now: float) -> None:
    """Raise ``ToolError`` if the last cold fetch of *branch* failed inside the probe-throttle window.

    Otherwise drops the expired marker.
    """
    _raise_if_attempt_throttled(
        branch,
        app_ctx.schema_cache_cold_failures.get(branch),
        config=app_ctx.config,
        now=now,
        what="the last schema fetch",
    )
    # Not throttled, so any marker for this branch is past its window and
    # throttles nothing from here on: drop it rather than wait for the sweep
    # that the next cold failure anywhere runs.
    app_ctx.schema_cache_cold_failures.pop(branch, None)


def _check_circuit_break(
    entry: CachedSchemaEntry,
    *,
    config: ServerConfig,
    branch: str,
    now: float,
    msg_suffix: str,
) -> None:
    """Raise ``ToolError`` if *entry* has crossed a circuit-break threshold.

    Called after a revalidation attempt, so a broken entry is always retried
    before a read is rejected.
    """
    if not _is_circuit_broken(
        entry,
        max_consecutive_failures=config.schema_cache_max_consecutive_failures,
        max_staleness_seconds=config.schema_cache_max_staleness_seconds,
        now=now,
    ):
        return
    _raise_schema_unavailable(branch, msg_suffix)


def _try_serve_from_cache(
    *,
    app_ctx: AppContext,
    client: InfrahubClient,
    resolved_branch: str,
    force_revalidate: bool,
    metrics: Any,
) -> CachedSchemaEntry | None:
    """Return an entry that can be served without the branch lock, or ``None`` to continue.

    - Served (``hit``): inside the skip-window, or inside the forced-revalidation
      debounce when *force_revalidate* is set.
    - Served stale (``stale_hit``): the last probe failed inside the
      probe-throttle window.
    - ``ToolError``: a cold or circuit-broken branch whose last attempt failed
      inside that window.

    Only a caller whose credential Infrahub accepted is served
    (:func:`_caller_is_validated`). An unvalidated passthrough caller gets
    ``None`` and probes with its own credential. :func:`_ensure_entry` calls this
    again under the lock, so waiters reuse the result of the probe ahead of them.
    """
    config = app_ctx.config
    now = _now()
    entry = app_ctx.schema_cache.get(resolved_branch)
    if entry is None:
        _raise_if_cold_fetch_throttled(app_ctx, branch=resolved_branch, now=now)
        return None

    throttle_seconds = _recovery_probe_seconds(config)
    if _is_circuit_broken(
        entry,
        max_consecutive_failures=config.schema_cache_max_consecutive_failures,
        max_staleness_seconds=config.schema_cache_max_staleness_seconds,
        now=now,
    ):
        if _is_retry_throttled(entry.last_attempt_monotonic, throttle_seconds=throttle_seconds, now=now):
            _raise_schema_unavailable(resolved_branch, _CIRCUIT_BREAK_MSG)
        return None

    if not _caller_is_validated(app_ctx, client, resolved_branch):
        # Infrahub has not seen this passthrough caller's credential: it probes
        # with it, outside the lock (see _validate_caller_outside_lock). That
        # probe runs concurrently with other callers' probes, so a recent
        # failure is no reason to fail this caller closed before it has tried.
        return None
    throttled = bool(entry.consecutive_failures) and _is_retry_throttled(
        entry.last_attempt_monotonic, throttle_seconds=throttle_seconds, now=now
    )

    current = (
        _is_forced_probe_debounced(entry, now=now)
        if force_revalidate
        else _is_within_skip_window(entry, skip_window_seconds=config.schema_cache_ttl, now=now)
    )
    if current:
        if metrics is not None:
            metrics.record_schema_cache_event("hit")
        _touch(app_ctx, resolved_branch)
        _install_into_client(client, entry)
        return entry

    if throttled:
        # Past the skip-window (or the forced debounce), but the last probe
        # failed moments ago: probing again would only serialize this read
        # behind another upstream timeout. Serve stale — the documented
        # transient-failure semantics — and let the first read to land after
        # the window do the next probe.
        if metrics is not None:
            metrics.record_schema_cache_event("stale_hit")
        _touch(app_ctx, resolved_branch)
        _install_into_client(client, entry)
        return entry
    return None


def _fast_validation_candidate(
    app_ctx: AppContext, client: InfrahubClient, resolved_branch: str
) -> CachedSchemaEntry | None:
    """Return the entry an unvalidated passthrough caller can check without the lock, or ``None``.

    Requires an unvalidated caller and an entry that exists and is not
    circuit-broken. Cold fetches and recovery probes stay under the lock.
    """
    if _caller_is_validated(app_ctx, client, resolved_branch):
        return None
    entry = app_ctx.schema_cache.get(resolved_branch)
    if entry is None:
        return None
    config = app_ctx.config
    if _is_circuit_broken(
        entry,
        max_consecutive_failures=config.schema_cache_max_consecutive_failures,
        max_staleness_seconds=config.schema_cache_max_staleness_seconds,
        now=_now(),
    ):
        return None
    return entry


def _fail_unvalidated_probe(app_ctx: AppContext, branch: str, exc: Exception, metrics: Any) -> NoReturn:
    """Count a failed lock-free probe once, then fail the unvalidated caller with ``ToolError``.

    The caller is not served the stale entry because its credential was never
    checked. An entry removed during the probe is not put back.
    """
    current = app_ctx.schema_cache.get(branch)
    if current is not None:
        _note_failure(app_ctx=app_ctx, entry=current, metrics=metrics, now=_now())
    logger.warning("schema_cache_revalidate_failure branch=%s exception=%r", branch, exc)
    _raise_schema_unavailable(
        branch,
        f"schema revalidation failed and this caller's credential could not be checked. {_UNREACHABLE_HINT}",
    )


async def _validate_caller_outside_lock(
    *,
    app_ctx: AppContext,
    client: InfrahubClient,
    resolved_branch: str,
    metrics: Any,
) -> CachedSchemaEntry | None:
    """Check an unvalidated passthrough caller's credential with a ``/summary`` probe, without the lock.

    Each probe carries its caller's credential, so concurrent probes cannot be
    merged into one. Outside the lock they run at the same time.

    - Hash matches: serve the entry.
    - Hash differs: return ``None``. The refetch runs under the lock.
    - Branch gone: drop the entry and raise ``BranchNotFoundError``.
    - Rejected credential: raise ``AuthenticationError`` and leave the cache unchanged.
    - Any other failure: :func:`_fail_unvalidated_probe`.
    """
    entry = _fast_validation_candidate(app_ctx, client, resolved_branch)
    if entry is None:
        return None

    try:
        upstream_hash = await _fetch_summary_hash(client, resolved_branch)
    except _BranchGoneError as exc:
        # No lock is held here: a lock holder probing the same branch may drop
        # it too, which ``_drop_entry`` tolerates.
        _drop_entry(app_ctx, resolved_branch)
        logger.warning("schema_cache_branch_gone branch=%s", resolved_branch)
        raise BranchNotFoundError(identifier=resolved_branch) from exc
    except Exception as exc:  # noqa: BLE001
        if _is_auth_error(exc):
            _raise_auth_error(exc, branch=resolved_branch)
        _fail_unvalidated_probe(app_ctx, resolved_branch, exc, metrics)

    entry = app_ctx.schema_cache.get(resolved_branch)
    if entry is None or upstream_hash != entry.schema_hash:
        return None

    refreshed = _store_hash_match(app_ctx, entry, metrics)
    _install_into_client(client, refreshed)
    return refreshed


async def _ensure_entry(
    *,
    ctx: Context,
    client: InfrahubClient,
    branch: str | None,
    force_revalidate: bool,
) -> CachedSchemaEntry:
    """Return a current entry for *branch*, fetching or revalidating it when needed.

    Tries, in order, to serve from the cache (:func:`_try_serve_from_cache`), to
    check a passthrough caller without the lock
    (:func:`_validate_caller_outside_lock`), then fetches or revalidates under
    the branch lock. *client* makes every upstream call and is primed with the
    result. An unvalidated passthrough caller whose probe failed is rejected
    instead of being served stale.
    """
    app_ctx = get_app_ctx(ctx)
    resolved_branch = await _resolve_branch(ctx, branch)
    config = app_ctx.config
    metrics = _get_metrics()

    hot_entry = _try_serve_from_cache(
        app_ctx=app_ctx,
        client=client,
        resolved_branch=resolved_branch,
        force_revalidate=force_revalidate,
        metrics=metrics,
    )
    if hot_entry is not None:
        return hot_entry

    validated_entry = await _validate_caller_outside_lock(
        app_ctx=app_ctx,
        client=client,
        resolved_branch=resolved_branch,
        metrics=metrics,
    )
    if validated_entry is not None:
        return validated_entry

    async with _branch_lock(app_ctx, resolved_branch):
        # Re-read after acquiring the branch lock — another waiter may have populated.
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
        config=config,
        branch=resolved_branch,
        now=_now(),
        msg_suffix="circuit-break threshold reached after revalidation failure.",
    )
    if new_entry.consecutive_failures and not _caller_is_validated(app_ctx, client, resolved_branch):
        # A success zeroes the counter, so a non-zero one means *this*
        # attempt failed transiently — and it was this passthrough caller's
        # own probe, so its credential is still unchecked. It is not handed
        # the stale entry, and its client stays unprimed, so a further read
        # in this request probes again with its own credential.
        _raise_schema_unavailable(
            resolved_branch,
            f"schema revalidation failed and this caller's credential could not be checked. {_UNREACHABLE_HINT}",
        )
    _install_into_client(client, new_entry)
    return new_entry


def _get_metrics() -> Any:
    """Return the metrics middleware instance, or None if not configured.

    Imported inside the function so that this module can be imported without the
    middleware stack.
    """
    from infrahub_mcp.middleware import get_metrics  # noqa: PLC0415  # pylint: disable=import-outside-toplevel

    return get_metrics()


def _sdk_branch(client: InfrahubClient, branch: str | None) -> str:
    """Return *branch*, or ``client.default_branch`` when it is empty, as the SDK resolves it.

    The SDK looks up its cache under that name, so any other default would miss.
    """
    return branch or client.default_branch


async def _sdk_cached_branch_schema(client: InfrahubClient, branch: str) -> BranchSchema:
    """Return *branch* from *client*'s SDK cache, fetching and storing it on a miss.

    The ``schema_cache_enabled=False`` path. ``client.schema._fetch`` does not use
    the SDK cache, so calling it alone would fetch on every read.
    """
    cached = client.schema.cache.get(branch)
    if cached is not None:
        return cached
    branch_schema = await client.schema._fetch(branch=branch)  # noqa: SLF001  # pylint: disable=protected-access
    client.schema.set_cache(schema=branch_schema, branch=branch)
    return branch_schema


async def get_cached_branch_schema(
    ctx: Context,
    branch: str | None = None,
    *,
    client: InfrahubClient | None = None,
) -> BranchSchema:
    """Return the ``BranchSchema`` of *branch* (the default branch when ``None``).

    Also primes *client*'s SDK schema cache for *branch*, so its later
    ``client.schema`` and ``client.filters`` calls in this request need no
    fetch. Pass the client the tool goes on to use: in the passthrough modes
    ``get_client`` builds a new client on every call. When *client* is omitted,
    one client is resolved here.

    With ``schema_cache_enabled=False`` only the SDK's per-client cache is used.
    """
    app_ctx = get_app_ctx(ctx)
    client = resolve_client(ctx, client)
    if not app_ctx.config.schema_cache_enabled:
        return await _sdk_cached_branch_schema(client, _sdk_branch(client, branch))

    entry = await _ensure_entry(ctx=ctx, client=client, branch=branch, force_revalidate=False)
    return entry.schema


def _raise_if_sdl_fill_throttled(entry: CachedSchemaEntry, *, config: ServerConfig, now: float) -> None:
    """Raise ``ToolError`` if *entry*'s last SDL fetch failed inside the probe-throttle window."""
    _raise_if_attempt_throttled(
        entry.branch,
        entry.graphql_sdl_last_failure_monotonic,
        config=config,
        now=now,
        what="the GraphQL SDL fetch",
    )


async def _fill_graphql_sdl(*, app_ctx: AppContext, client: InfrahubClient, branch: str) -> str:
    """Fetch the SDL of *branch* and store it on the entry.

    Runs under the branch's SDL lock, so concurrent reads cost one fetch. The SDL
    is stored only if the entry still holds the same ``BranchSchema``
    (:func:`_same_snapshot`). A failure is raised and stamped on the entry, so
    SDL reads fail fast for the probe-throttle window. It does not count toward
    the circuit breaker. A rejected credential stamps nothing.
    """
    config = app_ctx.config
    entry = app_ctx.schema_cache.get(branch)
    if entry is not None:
        _raise_if_sdl_fill_throttled(entry, config=config, now=_now())
    async with app_ctx._schema_sdl_locks.hold(branch):  # noqa: SLF001
        entry = app_ctx.schema_cache.get(branch)
        if entry is not None:
            if entry.graphql_sdl is not None:
                return entry.graphql_sdl
            _raise_if_sdl_fill_throttled(entry, config=config, now=_now())
        try:
            sdl = await _fetch_graphql_sdl(client, branch)
        except Exception as exc:
            if _is_auth_error(exc):
                _raise_auth_error(exc, branch=branch)
            current = _same_snapshot(app_ctx, branch, entry)
            if current is not None:
                _store_entry(app_ctx, replace(current, graphql_sdl_last_failure_monotonic=_now()))
            logger.warning("schema_cache_sdl_fill_failure branch=%s exception=%r", branch, exc)
            raise
        current = _same_snapshot(app_ctx, branch, entry)
        if current is not None:
            _store_entry(app_ctx, replace(current, graphql_sdl=sdl))
        return sdl


def _same_snapshot(app_ctx: AppContext, branch: str, entry: CachedSchemaEntry | None) -> CachedSchemaEntry | None:
    """Return *branch*'s current entry if it still holds *entry*'s ``BranchSchema`` snapshot, else ``None``.

    A hash-match refresh replaces the entry object but keeps its ``schema``;
    a hash-diff refetch, a cold re-fetch or an eviction does not.
    """
    if entry is None:
        return None
    current = app_ctx.schema_cache.get(branch)
    if current is None or current.schema is not entry.schema:
        return None
    return current


async def get_cached_graphql_sdl(
    ctx: Context,
    branch: str | None = None,
    *,
    client: InfrahubClient | None = None,
) -> str:
    """Return the GraphQL SDL of *branch* (the default branch when ``None``).

    When the entry has no SDL yet, a forced ``/summary`` probe first confirms the
    cached schema, then :func:`_fill_graphql_sdl` fetches the SDL, so both
    describe the same schema version. *client* makes every upstream call (see
    :func:`get_cached_branch_schema`). With ``schema_cache_enabled=False`` the
    SDL is fetched on every call.
    """
    app_ctx = get_app_ctx(ctx)
    client = resolve_client(ctx, client)
    if not app_ctx.config.schema_cache_enabled:
        sdk_branch = _sdk_branch(client, branch)
        try:
            return await _fetch_graphql_sdl(client, sdk_branch)
        except Exception as exc:
            if _is_auth_error(exc):
                _raise_auth_error(exc, branch=sdk_branch)
            raise

    entry = await _ensure_entry(ctx=ctx, client=client, branch=branch, force_revalidate=False)
    if entry.graphql_sdl is not None:
        return entry.graphql_sdl
    # The fill fetches the SDL as it is upstream now. Confirm the structured
    # snapshot is still current first, so the two cannot describe different
    # schema states: an entry inside its skip-window may predate a change.
    # The forced probe is debounced, so an entry fetched moments ago (the
    # usual case) is not probed again. A throttled fill fails first, so it
    # costs no probe either.
    _raise_if_sdl_fill_throttled(entry, config=app_ctx.config, now=_now())
    entry = await _ensure_entry(ctx=ctx, client=client, branch=entry.branch, force_revalidate=True)
    if entry.graphql_sdl is not None:
        return entry.graphql_sdl
    return await _fill_graphql_sdl(app_ctx=app_ctx, client=client, branch=entry.branch)


async def get_cached_kind(
    ctx: Context,
    kind: str,
    branch: str | None = None,
    *,
    client: InfrahubClient | None = None,
) -> MainSchemaTypesAPI:
    """Return the schema of *kind* on *branch*.

    When *kind* is not in the cached schema, forces one revalidation before
    raising ``SchemaNotFoundError``, so a kind added upstream inside the
    skip-window is found. The forced probe is debounced
    (:data:`_FORCED_REVALIDATE_DEBOUNCE_SECONDS`) and follows the failure
    throttle. *client* makes every upstream call (see
    :func:`get_cached_branch_schema`).
    """
    client = resolve_client(ctx, client)
    schema = await get_cached_branch_schema(ctx, branch=branch, client=client)
    nodes = schema.nodes
    if kind in nodes:
        return nodes[kind]

    # Lazy revalidation: kind absent, the cache may be stale. Debounced per
    # branch — see _FORCED_REVALIDATE_DEBOUNCE_SECONDS.
    app_ctx = get_app_ctx(ctx)
    if not app_ctx.config.schema_cache_enabled:
        # Caching off — defer to the SDK, which resolves the branch itself.
        return await client.schema.get(kind=kind, branch=branch or None)

    entry = await _ensure_entry(ctx=ctx, client=client, branch=branch, force_revalidate=True)
    if kind in entry.schema.nodes:
        return entry.schema.nodes[kind]
    raise SchemaNotFoundError(identifier=kind)
