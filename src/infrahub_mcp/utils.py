import asyncio
import os
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

from fastmcp import Context
from fastmcp.exceptions import ToolError
from infrahub_sdk.exceptions import GraphQLError
from infrahub_sdk.node import Attribute, InfrahubNode, RelatedNode, RelationshipManager

from infrahub_mcp.auth import get_passthrough_token, get_user_from_token
from infrahub_mcp.config import ServerConfig
from infrahub_mcp.constants import AUTH_MODE_TOKEN_PASSTHROUGH

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient

CURRENT_DIRECTORY = Path(__file__).parent.resolve()


@dataclass
class AppContext:
    """Application context held for the lifetime of an MCP connection."""

    client: "InfrahubClient | None"
    config: ServerConfig
    session_branch: str | None = field(default=None)
    _session_branch_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    passthrough_client: "InfrahubClient | None" = field(default=None)


def get_client(ctx: Context) -> "InfrahubClient":
    """Get the Infrahub client for the current session.

    In token-passthrough mode, creates a per-session ``InfrahubClient``
    using the token from the request header (fail-closed — raises
    ``ToolError`` when no token is present).

    In other modes, returns the shared lifespan client.
    """
    from infrahub_sdk.client import InfrahubClient  # noqa: PLC0415

    app_ctx: AppContext = ctx.request_context.lifespan_context  # type: ignore[union-attr]

    if app_ctx.config.auth_mode == AUTH_MODE_TOKEN_PASSTHROUGH:
        token = get_passthrough_token()
        if token is None:
            msg = "Authentication required: no Infrahub API token in request header."
            raise ToolError(msg)
        if app_ctx.passthrough_client is None:
            app_ctx.passthrough_client = InfrahubClient(
                address=os.environ["INFRAHUB_ADDRESS"],
                config={"api_token": token},
            )
        return app_ctx.passthrough_client

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
    app_ctx: AppContext = ctx.request_context.lifespan_context  # type: ignore[union-attr]
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


async def convert_node_to_dict(*, obj: InfrahubNode, branch: str | None, include_id: bool = False) -> dict[str, Any]:  # noqa: C901
    data = {}

    if include_id:
        data["index"] = obj.id or None

    for attr_name in obj._schema.attribute_names:  # noqa: SLF001
        attr: Attribute = getattr(obj, attr_name)
        data[attr_name] = str(attr.value)

    for rel_name in obj._schema.relationship_names:  # noqa: SLF001
        rel = getattr(obj, rel_name)
        if rel and isinstance(rel, RelatedNode):
            if not rel.initialized:
                await rel.fetch()
            related_node = obj._client.store.get(  # noqa: SLF001
                branch=branch,
                key=rel.peer.id,
                raise_when_missing=False,
            )
            if related_node:
                data[rel_name] = (
                    related_node.get_human_friendly_id_as_string(include_kind=True)
                    if related_node.hfid
                    else related_node.id
                )
        elif rel and isinstance(rel, RelationshipManager):
            peers: list[dict[str, Any]] = []
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
                    related_node = peer.peer
                peers.append(
                    related_node.get_human_friendly_id_as_string(include_kind=True)
                    if related_node.hfid
                    else related_node.id,
                )
            data[rel_name] = peers
    return data
