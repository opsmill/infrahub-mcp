from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastmcp import Context, FastMCP
from infrahub_sdk.client import InfrahubClient

from infrahub_mcp_server.branch import mcp as branch_mcp
from infrahub_mcp_server.gql import mcp as graphql_mcp
from infrahub_mcp_server.schema import mcp as schema_mcp


@dataclass
class AppContext:
    client: InfrahubClient


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:  # noqa: ARG001, RUF029
    """Manages application lifecycle with type-safe context for the FastMCP server."""
    client = InfrahubClient()
    try:
        yield AppContext(client=client)
    finally:
        pass


mcp = FastMCP("Infrahub MCP", lifespan=app_lifespan)
mcp.mount(branch_mcp)
mcp.mount(graphql_mcp)
mcp.mount(schema_mcp)


@mcp.tool
async def get_objects(ctx: Context, kind: str, filters: dict | None = None) -> list[str]:
    """Get all objects of a specific kind from Infrahub.

    To retrieve the list of available kinds, use the `get_schema_mapping` tool.
    To retrieve the list of available filters for a specific kind, use the `get_node_filters` tool.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client

    if filters:
        objects = await client.filters(kind=kind, **filters)
    else:
        objects = await client.all(kind=kind)

    return [obj.display_label for obj in objects]


@mcp.tool
async def get_node_filters(ctx: Context, kind: str) -> dict[str, Any]:
    """Retrieve all the available filters for a specific schema node kind."""
    client: InfrahubClient = ctx.request_context.lifespan_context.client

    schema = await client.schema.get(kind=kind)
    return {f"{attribute.name}__value": "String" for attribute in schema.attributes}
