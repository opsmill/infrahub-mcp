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
  served before reads fail closed. A broken entry is not terminal: reads
  retry revalidation so the cache recovers on its own once Infrahub is
  healthy again.
- Upstream probes are throttled to one per ``min(schema_cache_ttl, 30 s)``
  per branch from the first failure onward, whatever the breaker state:
  reads that land inside that window serve the stale entry (or, once the
  breaker has tripped, fail fast) instead of queueing on the cache lock
  behind their own upstream timeout. A failed *cold* fetch is remembered
  the same way, so an empty cache during an outage costs one upstream
  timeout per window rather than one per request.
- A rejected credential (HTTP 401/403, or the SDK's ``AuthenticationError``)
  is not a transient failure. In passthrough modes the credential belongs
  to the caller, so it says nothing about upstream health: the read raises
  ``AuthenticationError`` to that caller — it is not served the stale
  entry — and leaves the entry, its failure counter, the breaker and the
  cold-failure marker untouched, so other callers keep being served and
  the next one probes with its own credential.
- A kind absent from the cached ``BranchSchema`` forces one revalidation
  regardless of the skip-window, so a kind added upstream is found before
  the window elapses. Forced probes are debounced to one per
  ``_FORCED_REVALIDATE_DEBOUNCE_SECONDS`` per branch — any attempt counts,
  successful or failed — and honour the failure throttle above, so a tool
  call resolving several unknown kinds, or a burst of misses queued behind
  one probe, costs one ``/summary`` round-trip rather than one per kind.
- The GraphQL SDL (``GET /schema.graphql``) is fetched together with the
  structured schema so the two describe the same upstream state, but its
  failure is not fatal: the entry is stored with ``graphql_sdl=None`` and
  the structured-schema tools proceed, while ``infrahub://graphql-schema``
  fills the SDL lazily on its next read and fails alone if that fails too.

See ``specs/archive/20260504-203256-schema-cache/`` for the full design.
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

from infrahub_mcp.utils import AppContext, get_client, get_default_branch

if TYPE_CHECKING:
    from typing import Any, NoReturn

    from fastmcp import Context
    from infrahub_sdk.client import InfrahubClient
    from infrahub_sdk.schema import BranchSchema

    from infrahub_mcp.config import ServerConfig

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
    graphql_sdl: str | None
    """Raw GraphQL SDL for the branch, or ``None`` when only its fetch failed.

    The SDL is fetched together with ``schema`` so both come from the same
    upstream state, but it is the one field allowed to be absent: it has a
    single reader, :func:`get_cached_graphql_sdl`, which fills it lazily
    under the cache lock. ``schema`` itself is never optional — every
    structured-schema tool depends on it.
    """
    fetched_at_monotonic: float
    consecutive_failures: int = 0
    last_attempt_monotonic: float = 0.0
    """Monotonic time of the last upstream *attempt*, successful or not.

    Distinct from ``fetched_at_monotonic`` (last *success*, which drives the
    skip-window and the staleness threshold). Together with
    ``consecutive_failures`` this field throttles probes after a failure,
    whether or not the breaker has tripped: while the last attempt failed
    less than ``min(schema_cache_ttl, 30 s)`` ago, reads serve the stale
    entry (breaker not tripped) or fail fast (breaker tripped) instead of
    each queueing on the cache lock behind its own upstream timeout. On its
    own it also debounces the revalidations a kind miss forces (see
    :data:`_FORCED_REVALIDATE_DEBOUNCE_SECONDS`).
    """
    circuit_break_recorded: bool = False
    """Whether the current broken streak has already been counted.

    Keeps the ``circuit_break`` metric at one event per streak rather than
    one per blocked read. Any successful fetch or revalidation builds a
    fresh entry with this back to ``False``, so a later trip is counted
    again.
    """


# Status codes ``/api/schema/summary`` answers for a branch that no longer
# exists. Infrahub raises ``BranchNotFoundError`` (``HTTP_CODE = 400``) from
# the endpoint's branch dependency before the handler runs, so 400 is the
# code a deleted branch actually produces; the SDK's own
# ``_parse_schema_response`` maps 400 from ``/api/schema`` to
# ``BranchNotFoundError`` for the same reason. 404 stays accepted for a
# server that routes an unknown branch to a not-found response.
_BRANCH_GONE_STATUS_CODES: frozenset[int] = frozenset({httpx.codes.BAD_REQUEST, httpx.codes.NOT_FOUND})


class _BranchGoneError(Exception):
    """Raised by ``_fetch_summary_hash`` when ``/summary`` reports the branch as gone.

    "Gone" means the response status is one of
    :data:`_BRANCH_GONE_STATUS_CODES` (400 or 404).
    """


# Status codes that mean Infrahub rejected the *caller's* credential rather
# than failing the request: 401 (missing or invalid token) and 403 (token
# lacks the permission). The same pair ``InfrahubClient.execute_graphql``
# maps to ``AuthenticationError``.
_AUTH_STATUS_CODES: frozenset[int] = frozenset({httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN})


def _is_auth_error(exc: BaseException) -> bool:
    """Return True when *exc* means Infrahub rejected the caller's credential.

    In passthrough auth modes the credential belongs to the caller, so a
    401/403 is a property of that caller's request, not of upstream health,
    and must not be counted like a transient failure. Two shapes reach this
    module from the SDK (``infrahub_sdk`` 1.22.2):

    - ``httpx.HTTPStatusError`` whose ``response.status_code`` is 401 or
      403. ``InfrahubClient._get`` never raises on status:
      ``_default_request_method`` (``client.py``) maps only
      ``httpx.NetworkError`` and ``httpx.ReadTimeout`` to
      ``ServerNotReachableError`` / ``ServerNotResponsiveError`` and returns
      the response, and the ``@handle_relogin`` wrapper on ``_get`` only
      retries a 401 whose body says ``Expired Signature``. The status
      therefore surfaces from ``response.raise_for_status()`` — ours in
      :func:`_fetch_summary_hash` for ``/api/schema/summary``, the SDK's in
      ``InfrahubSchemaBase._parse_schema_response`` (``schema/__init__.py``)
      for ``/api/schema`` behind ``client.schema._fetch``. With
      username/password credentials (``basic-passthrough``) ``_get`` first
      awaits ``login()``, which raises the same type when
      ``POST /api/auth/login`` rejects the password.
    - ``infrahub_sdk.exceptions.AuthenticationError``, which
      ``login(refresh=True)`` raises when ``POST /api/auth/refresh`` answers
      anything but 401, and which ``execute_graphql`` maps 401/403 to — not
      on this module's path, but the type the rest of the server already
      surfaces for a rejected credential (``InfrahubConnectionMiddleware``).

    ``client.schema.get_graphql_schema`` raises a bare ``ValueError`` for any
    non-200, so an SDL-only auth failure cannot be told from an outage and
    :func:`_fill_graphql_sdl` handles it as transient.
    """
    if isinstance(exc, AuthenticationError):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in _AUTH_STATUS_CODES


def _raise_auth_error(exc: Exception, *, branch: str) -> NoReturn:
    """Surface a rejected credential to the caller as ``AuthenticationError``.

    Normalises the ``httpx.HTTPStatusError`` shape to the SDK's public
    exception so a bad token fails a schema read the same way it fails a
    GraphQL query — ``InfrahubConnectionMiddleware`` turns it into the
    "check your credentials" MCP error — instead of leaking a raw
    ``HTTPStatusError``; :func:`_revalidate_under_lock` normalises a gone
    branch to ``BranchNotFoundError`` for the same reason. Nothing about the
    entry, its counters, the breaker or the cold-failure marker is touched:
    this caller's credential was rejected, other callers are unaffected.
    The log line carries the status and the exception's repr, which names
    the URL and status only — the credential travels in request headers and
    is part of neither.
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
    if max_consecutive_failures and entry.consecutive_failures >= max_consecutive_failures:
        return True
    return bool(max_staleness_seconds and (now - entry.fetched_at_monotonic) >= max_staleness_seconds)


def _is_within_skip_window(entry: CachedSchemaEntry, *, skip_window_seconds: int, now: float) -> bool:
    if skip_window_seconds <= 0:
        return False
    return (now - entry.fetched_at_monotonic) < skip_window_seconds


def _is_retry_throttled(last_attempt_monotonic: float, *, throttle_seconds: int, now: float) -> bool:
    """Return True when an upstream attempt happened less than *throttle_seconds* ago.

    Callers consult this after a *failed* attempt, whatever the breaker
    state, so a failing branch costs one upstream timeout per window rather
    than one per request: before the breaker trips the read serves the
    stale entry, after it trips the read fails fast, and on a cold cache the
    read fails fast too. A ``throttle_seconds`` of 0 disables the throttle.
    """
    if throttle_seconds <= 0:
        return False
    return (now - last_attempt_monotonic) < throttle_seconds


_MAX_RECOVERY_PROBE_SECONDS = 30
"""Upper bound, in seconds, on the per-branch probe-throttle window.

The window is ``min(schema_cache_ttl, _MAX_RECOVERY_PROBE_SECONDS)`` and
applies after any failed upstream attempt — a failed revalidation probe or a
failed cold fetch — whether or not the breaker has tripped. Throttling by the
skip-window alone would tie recovery latency to a freshness knob: an operator
raising ``schema_cache_ttl`` to an hour to cut upstream load would also leave
a failing branch serving stale (or, once tripped, rejecting reads) for an
hour after Infrahub came back, which defeats the self-healing breaker.
Clamping bounds worst-case recovery at half a minute whatever the TTL, and
one probe per 30 s is negligible load even through a sustained outage —
probes are single-flight under the cache lock. ``schema_cache_ttl = 0`` still
disables the throttle entirely.
"""


def _recovery_probe_seconds(config: ServerConfig) -> int:
    """Return the probe-throttle window applied after a failed upstream attempt."""
    return min(config.schema_cache_ttl, _MAX_RECOVERY_PROBE_SECONDS)


_FORCED_REVALIDATE_DEBOUNCE_SECONDS = 2
"""Debounce, in seconds, on the revalidations a kind miss forces.

:func:`get_cached_kind` bypasses the skip-window when a kind is absent from
the cached ``BranchSchema``, so a kind added upstream is found before the
window elapses. Undebounced, every miss paid a ``/summary`` round-trip under
the cache lock even when the previous miss had just proved the cache
current. Misses are rare — ``BranchSchema.nodes`` already folds nodes,
generics, profiles and templates together, so a cached kind's relationship
peers are present — but they cluster: an agent retrying a mistyped kind,
``schema.py`` gathering ``get_cached_kind`` over peers and ``tools/nodes.py``
looping over them when a peer really is unknown, or concurrent misses queued
behind one probe. Two seconds coalesces one call's fan-out and a short retry
burst while staying far below the skip-window, so the case the forced probe
exists for still works: a miss more than 2 s after the previous attempt
probes, and a kind added upstream is found then. The value is deliberately
independent of ``schema_cache_ttl`` — with the skip-window off, the
``get_cached_branch_schema`` read that precedes every miss has itself just
probed, which makes the forced probe redundant anyway. Any attempt arms the
debounce; a failed one also arms the longer failure throttle, which forced
reads honour as well.
"""


def _is_forced_probe_debounced(entry: CachedSchemaEntry, *, now: float) -> bool:
    """Return True when any upstream attempt for *entry* landed inside the forced-revalidation debounce."""
    return (now - entry.last_attempt_monotonic) < _FORCED_REVALIDATE_DEBOUNCE_SECONDS


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

    Raises :class:`_BranchGoneError` on HTTP 400 or 404 (see
    :data:`_BRANCH_GONE_STATUS_CODES`) so the caller can evict the cache
    entry. Other HTTP errors propagate.

    The Infrahub SDK does not yet expose a public wrapper for this
    endpoint; the call uses ``client._get`` mirroring the existing
    pattern in ``resources/schema.py`` for the GraphQL SDL fetch.
    TODO: swap for ``client.schema.summary()`` once the upstream SDK PR
    lands.
    """
    # ``urlencode`` mirrors the SDK's ``client.schema._fetch``. Infrahub allows
    # ``#``, ``&``, ``+``, ``%`` and ``/`` in branch names; interpolated raw,
    # ``#`` drops the query as a fragment and ``&`` splits it, so ``/summary``
    # would answer for the default branch and its hash be compared against
    # this branch's cache entry.
    url = f"{client.address}/api/schema/summary?{urlencode([('branch', branch)])}"
    response = await client._get(url=url)  # noqa: SLF001  # pylint: disable=protected-access
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
    """Fetch the raw GraphQL SDL for *branch* via ``GET /schema.graphql``.

    The SDL is branch-specific and is cached alongside the structured
    ``BranchSchema`` for the same branch, so the branch must be threaded
    through — otherwise a non-default branch's schema would be paired with
    the default branch's SDL.
    """
    return await client.schema.get_graphql_schema(branch=branch)


async def _full_fetch(
    client: InfrahubClient,
    branch: str,
) -> tuple[BranchSchema, str | None]:
    """Fetch the full BranchSchema and, best-effort, the GraphQL SDL for a branch.

    Returns a ``(branch_schema, graphql_sdl)`` tuple. The two fetches
    happen sequentially — they are different endpoints and a small
    sequence keeps error attribution clear.

    A structured-schema failure propagates: nothing useful can be served
    without it. An SDL failure does not. ``/schema.graphql`` is a heavier
    endpoint with exactly one consumer (``infrahub://graphql-schema``), and
    letting it fail the whole fetch would take down every node and schema
    tool — and, on a cold cache, arm the cold-failure throttle — for an
    outage those tools never depend on. The SDL comes back as ``None`` with
    a WARN log instead, and :func:`get_cached_graphql_sdl` fills it lazily
    on its next read. The SDL is still fetched *here* on the healthy path
    rather than only lazily so it stays paired with the structured schema
    from the same upstream state; a lazy-only SDL could trail a hash flip
    by up to a skip-window.

    The SDK's public ``client.schema.fetch()`` returns only the kinds
    dict (``dict[str, MainSchemaTypes]``), not the ``BranchSchema``
    object that carries the schema hash we need for hash-validated
    revalidation. ``client.schema._fetch()`` is the inner method that
    returns the full ``BranchSchema`` — same protected-member precedent
    as the ``client._get`` calls used elsewhere in this module.
    TODO: swap for a public SDK accessor when one lands.
    """
    branch_schema: BranchSchema = await client.schema._fetch(branch=branch)  # noqa: SLF001  # pylint: disable=protected-access
    graphql_sdl: str | None
    try:
        graphql_sdl = await _fetch_graphql_sdl(client, branch)
    except Exception as exc:  # noqa: BLE001
        graphql_sdl = None
        logger.warning(
            "schema_cache_sdl_fetch_failure branch=%s exception=%r",
            branch,
            exc,
        )
    return branch_schema, graphql_sdl


def _record_circuit_break(metrics: Any, branch: str, threshold: str, age: float) -> None:
    """Record a circuit-break *transition* (entry newly crossed a threshold).

    Called once per transition, not once per blocked read, so the counter
    measures how often the breaker tripped rather than how many requests it
    rejected.
    """
    if metrics is not None:
        metrics.record_schema_cache_event("circuit_break")
    logger.error(
        "schema_cache_circuit_break branch=%s threshold=%s last_success_age_seconds=%.1f",
        branch,
        threshold,
        age,
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
    """Store a failure-incremented copy of *entry* and report a fresh break.

    Returns the stored entry. Emits the ``circuit_break`` metric/log at most
    once per broken streak — the first failed probe that leaves the entry
    broken — so the counter measures trips rather than rejected reads.
    A rejected credential never reaches here: both callers route it through
    :func:`_raise_auth_error` first, so one caller's bad token cannot move
    the counter or trip the breaker for everyone.
    """
    config = app_ctx.config
    max_failures = config.schema_cache_max_consecutive_failures
    max_staleness = config.schema_cache_max_staleness_seconds

    new_entry = replace(
        entry,
        consecutive_failures=entry.consecutive_failures + 1,
        last_attempt_monotonic=now,
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
            now - new_entry.fetched_at_monotonic,
        )
    app_ctx.schema_cache[entry.branch] = new_entry
    return new_entry


async def _cold_fetch_under_lock(
    *,
    app_ctx: AppContext,
    client: InfrahubClient,
    branch: str,
) -> CachedSchemaEntry:
    """Cold-fetch path: no entry exists for *branch*. Caller holds the lock.

    A failed structured-schema fetch is remembered in
    ``AppContext.schema_cache_cold_failures`` so reads landing inside the
    probe-throttle window fail fast instead of each paying an upstream
    timeout under the lock (see :func:`_raise_if_cold_fetch_throttled`); the
    failure itself still propagates unchanged to the caller.
    ``BranchNotFoundError`` is not remembered: an unknown branch is a fast,
    caller-specific answer rather than an upstream-health signal, and it
    must keep surfacing as ``BranchNotFoundError``. Nor is a rejected
    credential (:func:`_is_auth_error`): it is this caller's problem, so it
    surfaces as ``AuthenticationError`` and the next caller probes with its
    own credential instead of being failed fast by the marker. Every other
    failure — network, timeout, other 4xx, 5xx — is treated uniformly,
    matching the revalidation path (ADR 0009). An SDL-only failure never
    reaches this handler: :func:`_full_fetch` absorbs it and the entry is
    stored with ``graphql_sdl=None``, so the marker is not armed for it.
    """
    try:
        branch_schema, graphql_sdl = await _full_fetch(client, branch)
    except BranchNotFoundError:
        raise
    except Exception as exc:
        if _is_auth_error(exc):
            _raise_auth_error(exc, branch=branch)
        app_ctx.schema_cache_cold_failures[branch] = _now()
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
        schema_hash=branch_schema.hash or "",
        graphql_sdl=graphql_sdl,
        fetched_at_monotonic=now,
        consecutive_failures=0,
        last_attempt_monotonic=now,
    )
    app_ctx.schema_cache[branch] = entry
    app_ctx.schema_cache_cold_failures.pop(branch, None)
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

    On hash differ: full refetch and replace the entry. Only a
    structured-schema failure counts as a failed refetch below; an SDL-only
    failure keeps the fresh structured schema and stores the entry with
    ``graphql_sdl=None`` for :func:`get_cached_graphql_sdl` to fill later.

    On 400 or 404 from ``/summary`` (branch gone): evict the entry and
    raise the public :class:`~infrahub_sdk.exceptions.BranchNotFoundError`.
    The private ``_BranchGoneError`` never escapes this module, so a deleted
    branch fails the same way here as it does on a cold cache miss — where
    the SDK itself raises ``BranchNotFoundError`` from ``/api/schema``.

    On a rejected credential (:func:`_is_auth_error`) from either call:
    raise ``AuthenticationError`` to this caller and leave the entry exactly
    as it was — no failure counted, no attempt stamped, breaker unchanged.
    The caller asked upstream with a credential upstream rejected, so it is
    not handed the stale schema either; the entry stays servable for other
    callers, and the next one probes with its own credential.

    On any other failure (transient): preserve the existing entry's
    schema/hash/SDL but increment ``consecutive_failures`` and update
    nothing else. Emit WARN log. Return the (failure-incremented) entry.
    """
    branch = entry.branch
    try:
        upstream_hash = await _fetch_summary_hash(client, branch)
    except _BranchGoneError as exc:
        del app_ctx.schema_cache[branch]
        logger.warning("schema_cache_branch_gone branch=%s", branch)
        raise BranchNotFoundError(identifier=branch) from exc
    except Exception as exc:  # noqa: BLE001
        if _is_auth_error(exc):
            _raise_auth_error(exc, branch=branch)
        new_entry = _note_failure(app_ctx=app_ctx, entry=entry, metrics=metrics, now=_now())
        logger.warning(
            "schema_cache_revalidate_failure branch=%s exception=%r",
            branch,
            exc,
        )
        return new_entry

    if upstream_hash == entry.schema_hash:
        now = _now()
        refreshed = replace(
            entry,
            fetched_at_monotonic=now,
            consecutive_failures=0,
            last_attempt_monotonic=now,
            circuit_break_recorded=False,
        )
        app_ctx.schema_cache[branch] = refreshed
        if metrics is not None:
            metrics.record_schema_cache_event("hash_match")
        return refreshed

    # Hash differs — full refetch.
    try:
        branch_schema, graphql_sdl = await _full_fetch(client, branch)
    except Exception as exc:  # noqa: BLE001
        if _is_auth_error(exc):
            _raise_auth_error(exc, branch=branch)
        new_entry = _note_failure(app_ctx=app_ctx, entry=entry, metrics=metrics, now=_now())
        logger.warning(
            "schema_cache_refetch_failure branch=%s exception=%r",
            branch,
            exc,
        )
        return new_entry

    now = _now()
    refreshed = CachedSchemaEntry(
        branch=branch,
        schema=branch_schema,
        schema_hash=branch_schema.hash or upstream_hash,
        graphql_sdl=graphql_sdl,
        fetched_at_monotonic=now,
        consecutive_failures=0,
        last_attempt_monotonic=now,
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


_UNREACHABLE_HINT = "The Infrahub server may be unreachable; check server health and try again."
_CIRCUIT_BREAK_MSG = f"circuit-break threshold reached. {_UNREACHABLE_HINT}"


def _raise_schema_unavailable(branch: str, msg_suffix: str) -> NoReturn:
    msg = f"Schema temporarily unavailable for branch {branch!r}: {msg_suffix}"
    raise ToolError(msg)


def _raise_if_cold_fetch_throttled(app_ctx: AppContext, *, branch: str, now: float) -> None:
    """Fail fast when the last cold fetch for *branch* failed inside the probe-throttle window.

    With no entry to serve stale from, the only alternative to failing fast
    is taking the lock and probing again — exactly the one-timeout-per-
    request serialization the throttle exists to prevent. The marker is set
    by :func:`_cold_fetch_under_lock` and cleared by its next success; a read
    landing past the window falls through and probes again.
    """
    failed_at = app_ctx.schema_cache_cold_failures.get(branch)
    if failed_at is None:
        return
    window = _recovery_probe_seconds(app_ctx.config)
    if not _is_retry_throttled(failed_at, throttle_seconds=window, now=now):
        return
    elapsed = now - failed_at
    retry_in = math.ceil(window - elapsed)
    _raise_schema_unavailable(
        branch,
        f"the last schema fetch failed {elapsed:.0f} s ago; the next upstream attempt is in {retry_in} s. "
        f"{_UNREACHABLE_HINT}",
    )


def _check_circuit_break(
    entry: CachedSchemaEntry,
    *,
    config: ServerConfig,
    branch: str,
    now: float,
    msg_suffix: str = _CIRCUIT_BREAK_MSG,
) -> None:
    """Raise ``ToolError`` if *entry* has crossed a circuit-break threshold.

    Call this *after* a revalidation attempt: the breaker is a fail-closed
    exit for reads whose recovery attempt just failed, never a latch that
    rejects reads without trying upstream first. The ``circuit_break``
    metric is recorded at the transition in :func:`_note_failure`, not
    here, so it counts trips rather than rejected requests.
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
    """Hot-path attempt: return a servable entry without acquiring the cache lock.

    Returns the entry if it is within the skip-window (``hit``), or if it is
    past the skip-window but its last probe failed inside the probe-throttle
    window (served stale, ``stale_hit``). Returns ``None`` if the caller
    must take the lock: cold cache, past the skip-window with no recent
    failed probe, or a broken entry due for a recovery probe.

    ``force_revalidate`` — a kind miss in :func:`get_cached_kind` — swaps the
    skip-window for the much shorter forced-revalidation debounce: the entry
    is served (``hit``) when any upstream attempt landed less than
    :data:`_FORCED_REVALIDATE_DEBOUNCE_SECONDS` ago, otherwise the caller
    must probe. It bypasses the skip-window, not the probe budget: the
    failure throttle and the breaker apply to a forced read exactly as to a
    regular one, since a missing kind says nothing about upstream health.

    Raises ``ToolError`` when a probe would be pointless: a cold cache whose
    last fetch failed inside the window, or a circuit-broken entry whose
    last probe did. That keeps a failing branch — cold or warm, tripped or
    not — at one upstream timeout per window rather than one per request.
    A circuit-broken entry is otherwise neither served nor rejected
    outright: it falls through to the lock path so revalidation can heal it
    once Infrahub recovers.

    :func:`_ensure_entry` calls this again after acquiring the lock, so
    waiters queued behind a probe observe its outcome instead of repeating
    it: a failure serves them stale (or fails fast), and a forced probe's
    fresh attempt debounces the forced reads behind it.
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

    current = (
        _is_forced_probe_debounced(entry, now=now)
        if force_revalidate
        else _is_within_skip_window(entry, skip_window_seconds=config.schema_cache_ttl, now=now)
    )
    if current:
        if metrics is not None:
            metrics.record_schema_cache_event("hit")
        _install_into_client(client, entry)
        return entry

    if entry.consecutive_failures and _is_retry_throttled(
        entry.last_attempt_monotonic, throttle_seconds=throttle_seconds, now=now
    ):
        # Past the skip-window (or the forced debounce), but the last probe
        # failed moments ago: probing again would only serialize this read
        # behind another upstream timeout. Serve stale — the documented
        # transient-failure semantics — and let the first read to land after
        # the window do the next probe.
        if metrics is not None:
            metrics.record_schema_cache_event("stale_hit")
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
    via the cache lock, per-branch probe throttling after a failure (warm
    or cold), circuit-break thresholds, and branch-gone evicts.

    ``force_revalidate`` replaces the skip-window with the forced-revalidation
    debounce (see :data:`_FORCED_REVALIDATE_DEBOUNCE_SECONDS`) and leaves
    every other rule in place. The re-check under the lock makes forced reads
    single-flight too: the first miss to take the lock probes, and the misses
    queued behind it are served by that probe's attempt.
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
        config=config,
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


async def _sdk_cached_branch_schema(client: InfrahubClient, branch: str) -> BranchSchema:
    """Serve *branch* from the SDK's per-client cache, fetching and priming it on a miss.

    This is the ``schema_cache_enabled=False`` path, and it must reproduce
    the pre-feature baseline exactly: the SDK's ``client.schema.all()`` /
    ``get()`` populate ``client.schema.cache[branch]`` once and serve every
    later call from it. ``client.schema._fetch`` alone neither reads nor
    writes that cache, so calling it bare would refetch ``/api/schema`` on
    every request even on the shared lifespan client. ``set_cache`` always
    stores a ``BranchSchema`` (it normalises the other accepted shapes on
    write), so a hit can be returned as-is.
    """
    cached = client.schema.cache.get(branch)
    if cached is not None:
        return cached
    branch_schema = await client.schema._fetch(branch=branch)  # noqa: SLF001  # pylint: disable=protected-access
    client.schema.set_cache(schema=branch_schema, branch=branch)
    return branch_schema


async def get_cached_branch_schema(ctx: Context, branch: str | None = None) -> BranchSchema:
    """Return the cached ``BranchSchema`` for *branch* (default branch when None).

    Side effect: the per-request fresh ``InfrahubClient`` returned by
    :func:`infrahub_mcp.utils.get_client` has its per-client SDK schema
    cache populated for *branch* via ``client.schema.set_cache(...)``,
    so subsequent ``client.schema.all(branch=...)`` and
    ``client.schema.get(kind=..., branch=...)`` calls within this
    request are served from the SDK's in-memory cache.

    When ``schema_cache_enabled`` is False, the process-wide cache is
    bypassed and only the SDK's per-client cache is used (the pre-feature
    baseline): a client that already holds *branch* is served from
    ``client.schema.cache`` without an upstream call, otherwise the schema
    is fetched once and stored there. Shared-client auth modes therefore
    fetch once per process and never revalidate; passthrough modes, whose
    client is rebuilt per request, fetch once per request.
    """
    app_ctx = _get_app_ctx(ctx)
    if not app_ctx.config.schema_cache_enabled:
        client = get_client(ctx)
        resolved_branch = await _resolve_branch(ctx, branch)
        return await _sdk_cached_branch_schema(client, resolved_branch)

    entry = await _ensure_entry(ctx=ctx, branch=branch, force_revalidate=False)
    return entry.schema


async def _fill_graphql_sdl(*, app_ctx: AppContext, client: InfrahubClient, branch: str) -> str:
    """Fetch and store the SDL for an entry whose ``graphql_sdl`` is ``None``.

    Runs under the cache lock so a burst of ``infrahub://graphql-schema``
    reads behind a missing SDL costs one upstream fetch, and re-reads the
    entry first because a waiter ahead in the queue may have filled it.
    Every writer of ``schema_cache`` holds the same lock, so the entry read
    here is the one still stored when the fetch returns; the identity check
    before storing makes that invariant explicit rather than assumed and
    keeps a replaced or evicted entry from being resurrected.

    A failure propagates to the caller — the SDL resource fails on its own —
    and is deliberately not counted toward ``consecutive_failures`` or the
    breaker: the structured schema was just served successfully, so this
    says nothing about its freshness.
    """
    async with app_ctx._schema_cache_lock:  # noqa: SLF001
        entry = app_ctx.schema_cache.get(branch)
        if entry is not None and entry.graphql_sdl is not None:
            return entry.graphql_sdl
        sdl = await _fetch_graphql_sdl(client, branch)
        if entry is not None and app_ctx.schema_cache.get(branch) is entry:
            app_ctx.schema_cache[branch] = replace(entry, graphql_sdl=sdl)
        return sdl


async def get_cached_graphql_sdl(ctx: Context, branch: str | None = None) -> str:
    """Return the cached GraphQL SDL for *branch* (default branch when None).

    Shares the same hash gate as :func:`get_cached_branch_schema`; the
    SDL is invalidated together with the structured schema. When the
    entry's SDL is absent — its fetch failed while the structured schema
    succeeded — it is filled here under the cache lock, and a failure of
    that fill raises for this resource only. When ``schema_cache_enabled``
    is False, fetches fresh every call.
    """
    app_ctx = _get_app_ctx(ctx)
    if not app_ctx.config.schema_cache_enabled:
        client = get_client(ctx)
        resolved_branch = await _resolve_branch(ctx, branch)
        return await _fetch_graphql_sdl(client, resolved_branch)

    entry = await _ensure_entry(ctx=ctx, branch=branch, force_revalidate=False)
    if entry.graphql_sdl is not None:
        return entry.graphql_sdl
    return await _fill_graphql_sdl(app_ctx=app_ctx, client=get_client(ctx), branch=entry.branch)


async def get_cached_kind(ctx: Context, kind: str, branch: str | None = None) -> Any:
    """Return the schema for *kind* on *branch* with lazy refresh on miss.

    If the kind is missing from the cached BranchSchema, force one
    revalidation (bypassing the skip-window) before propagating
    :class:`SchemaNotFoundError`. This catches the case where the kind
    was added upstream after the cache was populated but before the
    skip-window elapsed.

    The forced revalidation is debounced: when any upstream attempt for the
    branch landed less than :data:`_FORCED_REVALIDATE_DEBOUNCE_SECONDS` ago,
    or its last attempt failed inside the probe-throttle window, the cached
    entry is used as-is and the miss raises without going upstream. A tool
    call that resolves several unknown kinds — ``schema.py`` gathers this
    over a kind's relationship peers, ``tools/nodes.py`` loops over them —
    therefore costs at most one ``/summary`` round-trip, as does a burst of
    misses for a mistyped kind.
    """
    schema = await get_cached_branch_schema(ctx, branch=branch)
    nodes = schema.nodes
    if kind in nodes:
        return nodes[kind]

    # Lazy revalidation: kind absent, the cache may be stale. Debounced per
    # branch — see _FORCED_REVALIDATE_DEBOUNCE_SECONDS.
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
