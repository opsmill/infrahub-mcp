import asyncio
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

from fastmcp import Context
from fastmcp.exceptions import ToolError
from infrahub_sdk.node import Attribute, InfrahubNode, RelatedNode, RelationshipManager

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient

CURRENT_DIRECTORY = Path(__file__).parent.resolve()


@dataclass
class AppContext:
    """Application context held for the lifetime of an MCP connection."""

    client: "InfrahubClient"
    session_branch: str | None = field(default=None)
    _session_branch_lock: asyncio.Lock = field(default_factory=asyncio.Lock)


async def get_or_create_session_branch(ctx: Context) -> str:
    """Return the session branch, auto-creating it on the first write of the session.

    Branch name format: ``mcp/session-YYYYMMDD-<8 hex chars>``.
    """
    app_ctx: AppContext = ctx.request_context.lifespan_context  # type: ignore[union-attr]
    async with app_ctx._session_branch_lock:  # noqa: SLF001
        if app_ctx.session_branch is None:
            slug = secrets.token_hex(4)
            date = datetime.now(UTC).strftime("%Y%m%d")
            branch_name = f"mcp/session-{date}-{slug}"
            await ctx.info(f"Auto-creating session branch: {branch_name}")
            await app_ctx.client.branch.create(branch_name=branch_name, sync_with_git=False, background_execution=False)
            app_ctx.session_branch = branch_name
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
