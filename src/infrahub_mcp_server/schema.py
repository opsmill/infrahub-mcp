from typing import TYPE_CHECKING

from fastmcp import Context, FastMCP

from infrahub_mcp_server.constants import NAMESPACES_INTERNAL

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClient

mcp: FastMCP = FastMCP(name="Infrahub Schema")


@mcp.tool
async def schema_get_mapping(ctx: Context) -> dict[str, str]:
    """List all schema nodes in Infrahub"""
    client: InfrahubClient = ctx.request_context.lifespan_context.client

    schema = await client.schema.all()
    return {kind: node.label or "" for kind, node in schema.items() if node.namespace not in NAMESPACES_INTERNAL}


@mcp.tool
async def schema_get(ctx: Context, kind: str) -> dict[str, str]:
    """Return the full schema for a specific kind."""
    client: InfrahubClient = ctx.request_context.lifespan_context.client

    schema = await client.schema.get(kind=kind)
    return schema.model_dump()
