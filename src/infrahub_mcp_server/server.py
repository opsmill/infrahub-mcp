from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastmcp import Context, FastMCP
from infrahub_sdk import InfrahubClient

from infrahub_mcp_server.constants import NAMESPACES_INTERNAL


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

schema_attribute_type_mapping = {
    "Text": "String",
    "Number": "Integer",
    "Boolean": "Boolean",
}


@mcp.tool
async def get_objects(ctx: Context, kind: str, filters: dict | None = None) -> list[str]:
    """Get all objects of a specific kind from Infrahub.

    To retrieve the list of available kinds, use the `list_schema_nodes` tool.
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
    """Retrieve all the available filters for a specific schema node kind.

    There's multiple types of filters
    attribute filters are in the form attribute__value

    relationship filters are in the form relationship__attribute__value
    you can find more information on the peer node of the relationship using the `get_schema` tool

    Filters that start with parent refer to a related generic schema node.
    You can find the type of that related node by inspected the output of the `get_schema` tool.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client

    schema = await client.schema.get(kind=kind)
    filters = {
        f"{attribute.name}__value": schema_attribute_type_mapping.get(attribute.kind, "String")
        for attribute in schema.attributes
    }

    for relationship in schema.relationships:
        relationship_schema = await client.schema.get(kind=relationship.peer)
        relationship_filters = {
            f"{relationship.name}__{attribute.name}__value": schema_attribute_type_mapping.get(attribute.kind, "String")
            for attribute in relationship_schema.attributes
        }
        filters.update(relationship_filters)

    return filters


@mcp.tool
async def get_schema_mapping(ctx: Context) -> dict[str, str]:
    """List all schema nodes in Infrahub"""
    client: InfrahubClient = ctx.request_context.lifespan_context.client

    schema = await client.schema.all()
    return {kind: node.label or "" for kind, node in schema.items() if node.namespace not in NAMESPACES_INTERNAL}


@mcp.tool
async def get_schema(ctx: Context, kind: str) -> dict[str, str]:
    """Return the full schema for a specific kind."""
    client: InfrahubClient = ctx.request_context.lifespan_context.client

    schema = await client.schema.get(kind=kind)
    return schema.model_dump()


@mcp.tool
async def get_graphql_schema(ctx: Context) -> str:
    """Retrieve the GraphQL schema from Infrahub"""
    client: InfrahubClient = ctx.request_context.lifespan_context.client
    resp = await client._get(url=f"{client.address}/schema.graphql")  # noqa: SLF001
    return resp.text


@mcp.tool
async def query_graphql(ctx: Context, query: str) -> dict:
    """Execute a GraphQL query against Infrahub."""
    client: InfrahubClient = ctx.request_context.lifespan_context.client
    return await client.execute_graphql(query=query)
