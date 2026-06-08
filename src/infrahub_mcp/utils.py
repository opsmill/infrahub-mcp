import asyncio
import os
import re
import secrets
import string
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn
from weakref import WeakKeyDictionary

from fastmcp import Context
from fastmcp.exceptions import ToolError
from infrahub_sdk import Config
from infrahub_sdk.branch import BranchStatus
from infrahub_sdk.client import InfrahubClient
from infrahub_sdk.exceptions import BranchNotFoundError, GraphQLError, NodeNotFoundError
from infrahub_sdk.exceptions import Error as SdkError
from infrahub_sdk.node import Attribute, InfrahubNode, RelatedNode, RelationshipManager

from infrahub_mcp.auth import (
    assert_writable_branch,
    get_passthrough_basic,
    get_passthrough_token,
    get_user_from_token,
)
from infrahub_mcp.config import ServerConfig
from infrahub_mcp.constants import AUTH_MODE_BASIC_PASSTHROUGH, AUTH_MODE_TOKEN_PASSTHROUGH

CURRENT_DIRECTORY = Path(__file__).parent.resolve()


_UNWRITABLE_STATUSES = frozenset({BranchStatus.MERGED, BranchStatus.DELETING})


@dataclass
class AppContext:
    """Application context shared for the lifetime of the MCP server process.

    The active session branch is tracked **per MCP session/connection**, not
    process-wide: the branch name and its lock are keyed by the per-session
    object in ``WeakKeyDictionary`` maps. Entries are released automatically when
    a session ends (no unbounded growth), and a reset/recovery in one session
    never disturbs another. ``default_branch`` stays instance-wide.
    """

    client: InfrahubClient | None
    config: ServerConfig
    default_branch: str | None = field(default=None)
    _default_branch_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _session_branches: WeakKeyDictionary[object, str] = field(default_factory=WeakKeyDictionary)
    _session_locks: WeakKeyDictionary[object, asyncio.Lock] = field(default_factory=WeakKeyDictionary)
    _session_locks_guard: asyncio.Lock = field(default_factory=asyncio.Lock)


def get_client(ctx: Context) -> InfrahubClient:
    """Get the Infrahub client for the current request.

    In token-passthrough mode, creates a **fresh** ``InfrahubClient``
    for every call using the token from the current request's ContextVar
    (fail-closed — raises ``ToolError`` when no token is present).
    No caching: each request's token is used exactly once so that
    different callers never share credentials.

    In other modes, returns the shared lifespan client.
    """
    if ctx.request_context is None:
        msg = "request_context must not be None"
        raise RuntimeError(msg)
    app_ctx: AppContext = ctx.request_context.lifespan_context

    if app_ctx.config.auth_mode in {AUTH_MODE_TOKEN_PASSTHROUGH, AUTH_MODE_BASIC_PASSTHROUGH}:
        address = os.environ.get("INFRAHUB_ADDRESS")
        if not address:
            msg = (
                "INFRAHUB_ADDRESS is required. "
                "Set it to the URL of your Infrahub instance (e.g. http://localhost:8000)."
            )
            raise ToolError(msg)

        if app_ctx.config.auth_mode == AUTH_MODE_TOKEN_PASSTHROUGH:
            token = get_passthrough_token()
            if token is None:
                msg = "Authentication required: no Infrahub API token in request header."
                raise ToolError(msg)
            return InfrahubClient(config=Config(address=address, api_token=token))

        credentials = get_passthrough_basic()
        if credentials is None:
            msg = (
                "Authentication required: no Basic credentials in request header. "
                "Send Authorization: Basic <base64(user:pass)>."
            )
            raise ToolError(msg)
        username, password = credentials
        return InfrahubClient(config=Config(address=address, username=username, password=password))

    if app_ctx.client is None:
        msg = "No Infrahub client available."
        raise ToolError(msg)
    return app_ctx.client


def _session_obj(ctx: Context) -> object:
    """Return the per-MCP-session object used to scope session-branch state.

    The session object is stable across tool calls within one client session and
    distinct across sessions, for every transport. Used as the key for the
    per-session ``WeakKeyDictionary`` maps on ``AppContext`` so state is isolated
    per session and released when the session ends.
    """
    if ctx.request_context is None or getattr(ctx.request_context, "session", None) is None:
        msg = "request_context.session must not be None"
        raise RuntimeError(msg)
    return ctx.request_context.session


async def _get_session_lock(app_ctx: AppContext, session: object) -> asyncio.Lock:
    """Return the per-session branch lock, creating it on first use."""
    async with app_ctx._session_locks_guard:  # noqa: SLF001
        lock = app_ctx._session_locks.get(session)  # noqa: SLF001
        if lock is None:
            lock = asyncio.Lock()
            app_ctx._session_locks[session] = lock  # noqa: SLF001
        return lock


def get_session_branch(ctx: Context) -> str | None:
    """Return the calling session's active branch, or ``None`` if none is set."""
    if ctx.request_context is None:
        msg = "request_context must not be None"
        raise RuntimeError(msg)
    app_ctx: AppContext = ctx.request_context.lifespan_context
    return app_ctx._session_branches.get(_session_obj(ctx))  # noqa: SLF001


_BRANCH_CHARSET = re.compile(r"[A-Za-z0-9._/-]+")
# Placeholder classes exclude '/' so a {user}/unknown placeholder can't greedily
# span the literal path separators of the pattern (e.g. "mcp/{user}/work").
_PLACEHOLDER_PATTERNS = {
    "date": r"\d{8}",
    "hex": r"[0-9a-f]{8}",
    "user": r"[A-Za-z0-9._-]+?",
}
_DEFAULT_PLACEHOLDER_PATTERN = r"[A-Za-z0-9._-]+?"


def branch_name_conforms(name: str, pattern: str) -> bool:
    """Return True if ``name`` matches the configured ``branch_pattern`` convention.

    Literal segments of the pattern must match exactly; placeholders match the
    shape they generate ({date}=8 digits, {hex}=8 lowercase hex, {user}=branch-safe
    characters, non-greedy). A pattern with no placeholders requires an exact
    match. The name must also use only allowed branch characters.
    """
    if _BRANCH_CHARSET.fullmatch(name) is None:
        return False
    regex_parts: list[str] = []
    for literal, field_name, _spec, _conv in string.Formatter().parse(pattern):
        regex_parts.append(re.escape(literal))
        if field_name:
            regex_parts.append(_PLACEHOLDER_PATTERNS.get(field_name, _DEFAULT_PLACEHOLDER_PATTERN))
    return re.fullmatch("".join(regex_parts), name) is not None


def _has_placeholders(pattern: str) -> bool:
    """Return True if the pattern contains supported placeholders."""
    return any(ph in pattern for ph in ("{date}", "{hex}", "{user}"))


def expand_branch_pattern(pattern: str, *, user_claim: str | None = None) -> str:
    """Expand placeholders in a branch naming pattern.

    Supported placeholders:
        {date} — current date as YYYYMMDD
        {hex}  — 8 random hex characters
        {user} — authenticated user from OIDC token, or 'anonymous'

    Args:
        pattern: Branch naming pattern with placeholders.
        user_claim: JWT claim to use for {user} resolution. When provided,
            attempts to read the OIDC token. When None, always uses 'anonymous'.
    """
    date = datetime.now(UTC).strftime("%Y%m%d")
    slug = secrets.token_hex(4)
    user = get_user_from_token(claim=user_claim) if user_claim is not None else "anonymous"
    return pattern.format(date=date, hex=slug, user=user)


def _is_branch_conflict(exc: GraphQLError) -> bool:
    """Return True if the GraphQL error indicates a branch name conflict."""
    msg = str(exc).lower()
    return "already exists" in msg or "unique" in msg or "duplicate" in msg


async def _create_branch_with_pattern(app_ctx: AppContext, ctx: Context) -> str:
    """Create a session branch from a pattern with placeholders, retrying on collision."""
    client = get_client(ctx)
    pattern = app_ctx.config.branch_pattern
    max_retries = app_ctx.config.max_branch_retries
    user_claim = app_ctx.config.oidc_user_claim if app_ctx.config.auth_mode == "oidc" else None
    for attempt in range(max_retries):
        branch_name = expand_branch_pattern(pattern, user_claim=user_claim)
        await ctx.info(f"Auto-creating session branch: {branch_name}")
        try:
            await client.branch.create(
                branch_name=branch_name,
                sync_with_git=False,
                wait_until_completion=True,
            )
            return branch_name
        except GraphQLError as exc:
            if not _is_branch_conflict(exc) or attempt == max_retries - 1:
                msg = (
                    f"Failed to create branch '{branch_name}' after "
                    f"{attempt + 1} attempt(s) using pattern '{pattern}': {exc}. "
                    "Retry; if it persists, the Infrahub branch API may be unavailable."
                )
                raise ToolError(msg) from exc
            # Collision — retry with a new hex

    msg = (
        f"Failed to generate a unique branch name after {max_retries} attempts "
        f"using pattern '{pattern}'. Try a pattern with {{hex}} for uniqueness."
    )
    raise ToolError(msg)


async def _create_branch_fixed(app_ctx: AppContext, ctx: Context) -> str:
    """Create a session branch with a fixed name (no placeholders)."""
    client = get_client(ctx)
    branch_name = app_ctx.config.branch_pattern
    await ctx.info(f"Auto-creating session branch: {branch_name}")
    try:
        await client.branch.create(
            branch_name=branch_name,
            sync_with_git=False,
            wait_until_completion=True,
        )
    except GraphQLError as exc:
        if _is_branch_conflict(exc):
            msg = (
                f"Branch '{branch_name}' already exists (it may have been merged and is now "
                "read-only). A fixed branch pattern cannot recover onto a fresh branch. "
                "Use a branch pattern with {hex} or {date} placeholders so recovery can create "
                "a unique branch, or delete the existing branch first."
            )
            raise ToolError(msg) from exc
        raise
    return branch_name


async def get_default_branch(ctx: Context) -> str:
    """Return the Infrahub default branch name, lazily resolved via the SDK and cached.

    Queries ``client.branch.all()`` and picks the branch with ``is_default=True``.
    Cached on the ``AppContext`` for the lifetime of the connection so we only
    pay the round-trip once per session. Falls back to ``main`` if the server
    does not advertise a default branch.
    """
    if ctx.request_context is None:
        msg = "request_context must not be None"
        raise RuntimeError(msg)
    app_ctx: AppContext = ctx.request_context.lifespan_context
    async with app_ctx._default_branch_lock:  # noqa: SLF001
        if app_ctx.default_branch is None:
            client = get_client(ctx)
            branches = await client.branch.all()
            default = next((b.name for b in branches.values() if b.is_default), "main")
            app_ctx.default_branch = default
    return app_ctx.default_branch


async def _stale_branch_reason(client: InfrahubClient, branch_name: str) -> str | None:
    """Return why a cached branch can't be reused, or ``None`` if it is writable.

    A single ``branch.get()`` validates the branch against Infrahub:
    - missing (deleted, merged-then-pruned, dev reset) -> ``BranchNotFoundError``
    - status MERGED / DELETING -> still present but read-only / being removed

    A merged branch is **not** deleted in Infrahub — it stays present and
    read-only — so existence alone is insufficient; the status must be checked.
    """
    try:
        branch = await client.branch.get(branch_name=branch_name)
    except BranchNotFoundError:
        return "no longer exists on Infrahub"
    if branch.status in _UNWRITABLE_STATUSES:
        return f"is read-only (status {branch.status.value})"
    return None


async def _provision_session_branch(app_ctx: AppContext, ctx: Context) -> str:
    """Create a new session branch using the configured pattern."""
    if _has_placeholders(app_ctx.config.branch_pattern):
        return await _create_branch_with_pattern(app_ctx, ctx)
    return await _create_branch_fixed(app_ctx, ctx)


async def get_or_create_session_branch(ctx: Context) -> str:
    """Return this session's branch, auto-creating it on the first write of the session.

    Scoped per MCP session (keyed by the session object). Uses the branch pattern
    from ``ServerConfig.branch_pattern``:
    - Patterns with placeholders ({date}, {hex}, {user}) are expanded.
      If creation fails due to a name conflict, a new {hex} is generated (up to max retries).
    - Fixed names (no placeholders) attempt a single creation.

    The cached branch is validated against Infrahub before reuse. If it has been
    deleted **or merged (now read-only)**, the cache is cleared and a fresh branch
    is provisioned automatically — the caller is warned, naming both the old and
    new branch — so writes recover without a server restart.
    """
    if ctx.request_context is None:
        msg = "request_context must not be None"
        raise RuntimeError(msg)
    app_ctx: AppContext = ctx.request_context.lifespan_context
    session = _session_obj(ctx)
    lock = await _get_session_lock(app_ctx, session)
    async with lock:
        current = app_ctx._session_branches.get(session)  # noqa: SLF001
        stale_reason: str | None = None
        if current is not None:
            stale_reason = await _stale_branch_reason(get_client(ctx), current)
            if stale_reason is not None:
                app_ctx._session_branches.pop(session, None)  # noqa: SLF001
        if current is None or stale_reason is not None:
            created = await _provision_session_branch(app_ctx, ctx)
            app_ctx._session_branches[session] = created  # noqa: SLF001
            if stale_reason is not None:
                await ctx.warning(
                    f"Session branch {current!r} {stale_reason}; recovered onto a new branch {created!r}."
                )
            return created
        return current


async def recover_if_session_branch_stale(ctx: Context) -> str | None:
    """Clear the calling session's branch if it is no longer writable; return the reason.

    Used by the write paths (FR-011) to recover from a branch merged/deleted *during*
    a write. The branch status is confirmed against Infrahub before anything is
    cleared — the write error text alone is ambiguous (a read-only *attribute* error
    also contains "read-only"). Returns ``"<branch> <reason>"`` when the cached branch
    was stale and has now been cleared, or ``None`` when it is still writable.
    """
    if ctx.request_context is None:
        msg = "request_context must not be None"
        raise RuntimeError(msg)
    app_ctx: AppContext = ctx.request_context.lifespan_context
    session = _session_obj(ctx)
    lock = await _get_session_lock(app_ctx, session)
    async with lock:
        branch = app_ctx._session_branches.get(session)  # noqa: SLF001
        if branch is None:
            return None
        reason = await _stale_branch_reason(get_client(ctx), branch)
        if reason is None:
            return None
        app_ctx._session_branches.pop(session, None)  # noqa: SLF001
        return f"{branch!r} {reason}"


async def reset_or_switch_session_branch(ctx: Context, branch: str | None) -> dict[str, Any]:
    """Reset or switch the calling session's branch (backs the ``reset_session_branch`` tool).

    - ``branch is None``: clear the cached branch so the next write provisions a fresh one.
    - ``branch`` given: point this session at it. Rejects the default branch and
      read-only/merged branches. If the branch does not exist and the name conforms
      to ``branch_pattern``, it is created; otherwise an actionable error is raised.

    Affects only the calling session.
    """
    if ctx.request_context is None:
        msg = "request_context must not be None"
        raise RuntimeError(msg)
    app_ctx: AppContext = ctx.request_context.lifespan_context
    session = _session_obj(ctx)
    lock = await _get_session_lock(app_ctx, session)
    async with lock:
        previous = app_ctx._session_branches.get(session)  # noqa: SLF001

        if branch is None:
            app_ctx._session_branches.pop(session, None)  # noqa: SLF001
            await ctx.info(f"Session branch reset (was {previous!r}); next write will create a new one.")
            return {"session_branch": None, "previous_branch": previous, "created": False, "action": "reset"}

        default_branch = await get_default_branch(ctx)
        try:
            assert_writable_branch(branch, default_branch=default_branch)
        except ValueError as exc:
            await _log_and_raise_error(ctx=ctx, error=str(exc))

        client = get_client(ctx)
        created = False
        try:
            existing = await client.branch.get(branch_name=branch)
        except BranchNotFoundError:
            if not branch_name_conforms(branch, app_ctx.config.branch_pattern):
                await _log_and_raise_error(
                    ctx=ctx,
                    error=f"Branch {branch!r} does not exist and does not match the configured "
                    f"branch pattern {app_ctx.config.branch_pattern!r}.",
                    remediation="Use a name that matches the pattern, or omit 'branch' to "
                    "auto-create a session branch.",
                )
            await ctx.info(f"Creating branch {branch!r} (matches the configured pattern).")
            try:
                await client.branch.create(branch_name=branch, sync_with_git=False, wait_until_completion=True)
            except GraphQLError as exc:
                await _log_and_raise_error(
                    ctx=ctx,
                    error=f"Failed to create branch {branch!r}: {exc}",
                    remediation="Choose a different name, or omit 'branch' to auto-create a session branch.",
                )
            created = True
        else:
            # Resolve is_default on the actual branch — robust against case/alias
            # variants that a name-only compare in assert_writable_branch would miss.
            if existing.is_default:
                await _log_and_raise_error(
                    ctx=ctx,
                    error=f"Branch {branch!r} resolves to the instance default branch; writes to it are not allowed.",
                    remediation="Use the session branch or a feature branch; merge via propose_changes.",
                )
            if existing.status in _UNWRITABLE_STATUSES:
                await _log_and_raise_error(
                    ctx=ctx,
                    error=f"Branch {branch!r} is read-only (status {existing.status.value}); "
                    "cannot target it for writes.",
                    remediation="Choose a writable branch, or omit 'branch' to create a fresh session branch.",
                )

        app_ctx._session_branches[session] = branch  # noqa: SLF001
        return {
            "session_branch": branch,
            "previous_branch": previous,
            "created": created,
            "action": "created" if created else "switched",
        }


async def _log_and_raise_error(ctx: Context, error: str | Exception, remediation: str | None = None) -> NoReturn:
    """Log an error and raise ToolError with remediation hint."""
    msg = str(error) if isinstance(error, Exception) else error
    await ctx.error(message=msg)
    if remediation:
        msg = f"{msg}\n\nRemediation: {remediation}"
    raise ToolError(msg)


def get_node_label(node: InfrahubNode, *, include_kind: bool = True) -> str:
    """Return the best human-readable label for a node.

    Preference order: display_label > HFID > node ID (UUID).
    """
    if node.display_label:
        return str(node.display_label)
    if node.hfid:
        return node.get_human_friendly_id_as_string(include_kind=include_kind) or "unknown"
    return node.id or "unknown"


async def convert_node_to_dict(  # noqa: C901  # pylint: disable=too-many-branches
    *,
    obj: InfrahubNode,
    branch: str | None,
    include_id: bool = False,
    hfid_include_kind: bool = True,
) -> dict[str, Any]:
    """Serialize an InfrahubNode into a plain dict with attributes and relationships."""
    data = {}

    if include_id:
        data["index"] = obj.id or None

    for attr_name in obj._schema.attribute_names:  # noqa: SLF001
        attr: Attribute = getattr(obj, attr_name)
        data[attr_name] = str(attr.value)

    for rel_name in obj._schema.relationship_names:  # noqa: SLF001
        rel = getattr(obj, rel_name)
        if rel and isinstance(rel, RelatedNode):
            if not rel.id:
                data[rel_name] = None
                continue
            if not rel.initialized:
                await rel.fetch()
            try:
                peer_node = rel.peer
            except (NodeNotFoundError, SdkError):
                data[rel_name] = rel.id
                continue
            related_node = obj._client.store.get(  # noqa: SLF001
                branch=branch,
                key=peer_node.id,
                raise_when_missing=False,
            )
            data[rel_name] = get_node_label(
                related_node or peer_node,
                include_kind=hfid_include_kind,
            )
        elif rel and isinstance(rel, RelationshipManager):
            peers: list[str] = []
            if not rel.initialized:
                await rel.fetch()
            for peer in rel.peers:
                # FIXME: We are using the store to avoid doing to many queries to Infrahub
                # but we could end up doing store+infrahub if the store is not populated
                related_node = obj._client.store.get(  # noqa: SLF001
                    key=peer.id,
                    raise_when_missing=False,
                    branch=branch,
                )
                if not related_node:
                    await peer.fetch()
                    try:
                        related_node = peer.peer
                    except NodeNotFoundError:
                        peers.append(peer.id)
                        continue
                peers.append(get_node_label(related_node, include_kind=hfid_include_kind))
            data[rel_name] = peers
    return data
