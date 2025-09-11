from typing import TYPE_CHECKING, Annotated, Any

from fastmcp import Context, FastMCP
from infrahub_sdk.exceptions import GraphQLError, SchemaNotFoundError
from infrahub_sdk.types import Order
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.constants import schema_attribute_type_mapping
from infrahub_mcp.utils import MCPResponse, MCPToolStatus, _log_and_return_error, convert_node_to_dict

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient

mcp: FastMCP = FastMCP(name="Infrahub Nodes")


@mcp.tool(tags={"nodes", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def get_nodes(
    ctx: Context,
    kind: Annotated[str, Field(description="Kind of the objects to retrieve.")],
    branch: Annotated[
        str | None,
        Field(default=None, description="Branch to retrieve the objects from. Defaults to None (uses default branch)."),
    ],
    filters: Annotated[dict[str, Any] | None, Field(default=None, description="Dictionary of filters to apply.")],
    partial_match: Annotated[bool, Field(default=False, description="Whether to use partial matching for filters.")],
) -> MCPResponse:
    """Get all objects of a specific kind from Infrahub.

    To retrieve the list of available kinds, use the `get_schema_mapping` tool.
    To retrieve the list of available filters for a specific kind, use the `get_node_filters` tool.

    Parameters:
        kind: Kind of the objects to retrieve.
        branch: Branch to retrieve the objects from. Defaults to None (uses default branch).
        filters: Dictionary of filters to apply.
        partial_match: Whether to use partial matching for filters.

    Returns:
        MCPResponse with success status and objects.

    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client
    await ctx.info(f"Fetching nodes of kind: {kind} with filters: {filters} from Infrahub...")

    # Verify if the kind exists in the schema and guide Tool if not
    try:
        schema = await client.schema.get(kind=kind, branch=branch)
    except SchemaNotFoundError:
        error_msg = f"Schema not found for kind: {kind}."
        remediation_msg = "Use the `get_schema_mapping` tool to list available kinds."
        return await _log_and_return_error(ctx=ctx, error=error_msg, remediation=remediation_msg)

    # TODO: Verify if the filters are valid for the kind and guide Tool if not

    try:
        if filters:
            await ctx.debug(f"Applying filters: {filters} with partial_match={partial_match}")
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
        return await _log_and_return_error(ctx=ctx, error=exc, remediation="Check the provided filters or the kind name.")

    # Format the response with serializable data
    # serialized_nodes = []
    # for node in nodes:
    #     node_data = await convert_node_to_dict(obj=node, branch=branch)
    #     serialized_nodes.append(node_data)
    serialized_nodes = [obj.display_label for obj in nodes]

    # Return the serialized response
    await ctx.debug(f"Retrieved {len(serialized_nodes)} nodes of kind {kind}")

    return MCPResponse(
        status=MCPToolStatus.SUCCESS,
        data=serialized_nodes,
    )


@mcp.tool(tags={"nodes", "filters", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def get_node_filters(
    ctx: Context,
    kind: Annotated[str, Field(description="Kind of the objects to retrieve.")],
    branch: Annotated[
        str | None,
        Field(default=None, description="Branch to retrieve the objects from. Defaults to None (uses default branch)."),
    ],
) -> MCPResponse:
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
        MCPResponse with success status and filters.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client
    await ctx.info(f"Fetching available filters for kind: {kind} from Infrahub...")

    # Verify if the kind exists in the schema and guide Tool if not
    try:
        schema = await client.schema.get(kind=kind, branch=branch)
    except SchemaNotFoundError:
        error_msg = f"Schema not found for kind: {kind}."
        remediation_msg = "Use the `get_schema_mapping` tool to list available kinds."
        return await _log_and_return_error(ctx=ctx, error=error_msg, remediation=remediation_msg)

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

    return MCPResponse(
        status=MCPToolStatus.SUCCESS,
        data=filters,
    )


@mcp.tool(tags={"nodes", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def get_related_nodes(
    ctx: Context,
    kind: Annotated[str, Field(description="Kind of the objects to retrieve.")],
    relation: Annotated[str, Field(description="Name of the relation to fetch.")],
    filters: Annotated[dict[str, Any] | None, Field(default=None, description="Dictionary of filters to apply.")],
    branch: Annotated[
        str | None,
        Field(default=None, description="Branch to retrieve the objects from. Defaults to None (uses default branch)."),
    ],
) -> MCPResponse:
    """Retrieve related nodes by relation name and a kind.

    Args:
        kind: Kind of the node to fetch.
        filters: Filters to apply on the node to fetch.
        relation: Name of the relation to fetch.
        branch: Branch to fetch the node from. Defaults to None (uses default branch).

    Returns:
        MCPResponse with success status and objects.

    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client
    filters = filters or {}
    if branch:
        await ctx.info(f"Fetching nodes related to {kind} with filters {filters} in branch {branch} from Infrahub...")
    else:
        await ctx.info(f"Fetching nodes related to {kind} with filters {filters} from Infrahub...")

    try:
        node_id = node_hfid = None
        if filters.get("ids"):
            node_id = filters["ids"][0]
        elif filters.get("hfid"):
            node_hfid = filters["hfid"]
        if node_id:
            node = await client.get(
                kind=kind,
                id=node_id,
                branch=branch,
                include=[relation],
                prefetch_relationships=True,
                populate_store=True,
            )
        elif node_hfid:
            node = await client.get(
                kind=kind,
                hfid=node_hfid,
                branch=branch,
                include=[relation],
                prefetch_relationships=True,
                populate_store=True,
            )
    except Exception as exc:  # noqa: BLE001
        return await _log_and_return_error(ctx=ctx, error=exc)

    rel = getattr(node, relation, None)
    if not rel:
        return await _log_and_return_error(
            ctx=ctx,
            error=f"Relation '{relation}' not found in kind '{kind}'.",
            remediation="Check the schema for the kind to confirm if the relation exists.",
        )
    peers = [
        await convert_node_to_dict(
            branch=branch,
            obj=peer.peer,
            include_id=True,
        )
        for peer in rel.peers
    ]

    return MCPResponse(
        status=MCPToolStatus.SUCCESS,
        data=peers,
    )
