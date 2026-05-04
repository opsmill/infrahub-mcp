import asyncio
import os
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

from fastmcp import Context
from fastmcp.exceptions import ToolError
from infrahub_sdk import Config
from infrahub_sdk.client import InfrahubClient
from infrahub_sdk.exceptions import Error as SdkError
from infrahub_sdk.exceptions import GraphQLError, NodeNotFoundError
from infrahub_sdk.node import Attribute, InfrahubNode, RelatedNode, RelationshipManager

from infrahub_mcp.auth import get_passthrough_basic, get_passthrough_token, get_user_from_token
from infrahub_mcp.config import ServerConfig
from infrahub_mcp.constants import AUTH_MODE_BASIC_PASSTHROUGH, AUTH_MODE_TOKEN_PASSTHROUGH

if TYPE_CHECKING:
    from infrahub_mcp.schema_cache import CachedSchemaEntry

CURRENT_DIRECTORY = Path(__file__).parent.resolve()


@dataclass
class AppContext:
    """Application context held for the lifetime of an MCP connection."""

    client: InfrahubClient | None
    config: ServerConfig
    session_branch: str | None = field(default=None)
    default_branch: str | None = field(default=None)
    _session_branch_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _default_branch_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    schema_cache: dict[str, "CachedSchemaEntry"] = field(default_factory=dict)
    _schema_cache_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


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
                background_execution=False,
            )
            return branch_name
        except GraphQLError as exc:
            if not _is_branch_conflict(exc) or attempt == max_retries - 1:
                msg = (
                    f"Failed to create branch '{branch_name}' after "
                    f"{attempt + 1} attempt(s) using pattern '{pattern}': {exc}"
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
            background_execution=False,
        )
    except GraphQLError as exc:
        if _is_branch_conflict(exc):
            msg = (
                f"Branch '{branch_name}' already exists. "
                "A fixed branch pattern cannot reuse an existing branch. "
                "Use a pattern with {hex} or {date} placeholders for unique branches, "
                "or delete the existing branch first."
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


async def get_or_create_session_branch(ctx: Context) -> str:
    """Return the session branch, auto-creating it on the first write of the session.

    Uses the branch pattern from ``ServerConfig.branch_pattern``:
    - Patterns with placeholders ({date}, {hex}, {user}) are expanded.
      If creation fails due to a name conflict, a new {hex} is generated (up to max retries).
    - Fixed names (no placeholders) attempt a single creation — if the branch
      already exists the server raises a clear error.

    Branch creation is attempted directly to avoid TOCTOU races between
    checking existence and creating.
    """
    if ctx.request_context is None:
        msg = "request_context must not be None"
        raise RuntimeError(msg)
    app_ctx: AppContext = ctx.request_context.lifespan_context
    async with app_ctx._session_branch_lock:  # noqa: SLF001
        if app_ctx.session_branch is None:
            if _has_placeholders(app_ctx.config.branch_pattern):
                app_ctx.session_branch = await _create_branch_with_pattern(app_ctx, ctx)
            else:
                app_ctx.session_branch = await _create_branch_fixed(app_ctx, ctx)
    return app_ctx.session_branch


async def _log_and_raise_error(ctx: Context, error: str | Exception, remediation: str | None = None) -> NoReturn:
    """Log an error and raise ToolError with remediation hint."""
    msg = str(error) if isinstance(error, Exception) else error
    await ctx.error(message=msg)
    if remediation:
        msg = f"{msg}\n\nRemediation: {remediation}"
    raise ToolError(msg)


def _node_label(node: InfrahubNode, *, include_kind: bool = True) -> str:
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
            data[rel_name] = _node_label(
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
                peers.append(_node_label(related_node, include_kind=hfid_include_kind))
            data[rel_name] = peers
    return data
