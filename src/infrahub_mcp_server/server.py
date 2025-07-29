from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastmcp import Context, FastMCP
from infrahub_sdk.client import InfrahubClient
from infrahub_sdk.exceptions import GraphQLError, SchemaNotFoundError
from infrahub_sdk.types import Order


from infrahub_mcp_server.branch import mcp as branch_mcp
from infrahub_mcp_server.gql import mcp as graphql_mcp
from infrahub_mcp_server.schema import mcp as schema_mcp
from infrahub_mcp_server.utils import _log_and_return_error, convert_node_to_dict

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

schema_attribute_type_mapping = {
    "Text": "String",
    "Number": "Integer",
    "Boolean": "Boolean",
}


@mcp.tool(tags=["nodes"])
async def get_nodes(
    ctx: Context,
    kind: str,
    branch: str | None = None,
    filters: dict | None = None,
    partial_match: bool = False,
) -> dict[str, Any]:
    """Get all objects of a specific kind from Infrahub.

    To retrieve the list of available kinds, use the `get_schema_mapping` tool.
    To retrieve the list of available filters for a specific kind, use the `get_node_filters` tool.

    Parameters:
        kind: Kind of the objects to retrieve.
        branch: Branch to retrieve the objects from. Defaults to None (uses default branch).
        filters: Dictionary of filters to apply.
        partial_match: Whether to use partial matching for filters.

    Returns:
        Dictionary of objects and metadata.

    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client
    ctx.info(f"Fetching nodes of kind: {kind} with filters: {filters} from Infrahub...")

    # Verify if the kind exists in the schema and guide Tool if not
    try:
        schema = await client.schema.get(kind=kind, branch=branch)
    except SchemaNotFoundError:
        error_msg = f"Schema not found for kind: {kind}."
        remediation_msg = "Use the `get_schema_mapping` tool to list available kinds."
        return _log_and_return_error(
            ctx=ctx,
            error=error_msg,
            remediation=remediation_msg
        )

    # TODO: Verify if the filters are valid for the kind and guide Tool if not

    try:
        if filters:
            nodes = await client.filters(
                kind=schema.kind,
                branch=branch,
                partial_match=partial_match,
                parallel=True,
                order=Order(disable=True),
                populate_store=True,
                prefetch_relationships=True,
                **filters,
            )
        else:
            nodes = await client.all(
                kind=schema.kind,
                branch=branch,
                parallel=True,
                order=Order(disable=True),
                populate_store=True,
                prefetch_relationships=True,
            )
    except GraphQLError as exc:
        return _log_and_return_error(
            ctx=ctx,
            error=exc,
            remediation="Check the provided filters or the kind name."
        )

    # Format the response with serializable data
    # serialized_nodes = []
    # for node in nodes:
    #     node_data = await convert_node_to_dict(obj=node, branch=branch)
    #     serialized_nodes.append(node_data)
    serialized_nodes = [obj.display_label for obj in nodes]

    # Return the serialized response
    ctx.debug(f"Retrieved {len(serialized_nodes)} nodes of kind {kind}")

    return {
        "success": True,
        "data": serialized_nodes,
    }

@mcp.tool(tags=["nodes", "filters"])
async def get_node_filters(
    ctx: Context,
    kind: str,
    branch: str | None = None,
) -> dict[str, Any]:
    """Retrieve all the available filters for a specific schema node kind.

    There's multiple types of filters
    attribute filters are in the form attribute__value

    relationship filters are in the form relationship__attribute__value
    you can find more information on the peer node of the relationship using the `get_schema` tool

    Filters that start with parent refer to a related generic schema node.
    You can find the type of that related node by inspected the output of the `get_schema` tool.

    Parameters:
        kind: Kind of the objects to retrieve.
        branch: Branch to retrieve the objects from. Defaults to None (uses default branch).

    Returns:
        Dictionary of filters.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client
    ctx.info(f"Fetching available filters for kind: {kind} from Infrahub...")

    # Verify if the kind exists in the schema and guide Tool if not
    try:
        schema = await client.schema.get(kind=kind, branch=branch)
    except SchemaNotFoundError:
        error_msg = f"Schema not found for kind: {kind}."
        remediation_msg = "Use the `get_schema_mapping` tool to list available kinds."
        return _log_and_return_error(
            ctx=ctx,
            error=error_msg,
            remediation=remediation_msg
        )

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

    return {
        "success": True,
        "data": filters,
    }
