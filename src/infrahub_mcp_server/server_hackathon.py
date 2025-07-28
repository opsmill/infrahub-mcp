from typing import TYPE_CHECKING

from fastmcp import Context, FastMCP
from infrahub_sdk.types import Order

from .utils import convert_node_to_dict

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClient

mcp = FastMCP("infrahub Hackathon MCP")


@mcp.tool
async def infrahub_get_nodes(
    *,
    ctx: Context,
    kind: str,
    branch: str | None = None,
    filters: dict | None = None,
    partial_match: bool = False,
) -> dict:
    """Retrieve objects from Infrahub.

    Args:
        kind: Kind of the objects to retrieve.
        branch: Branch to retrieve the objects from. Defaults to None (uses default branch).
        filters: Dictionary of filters to apply. Simple filters like {"name": "router1"} will be
                automatically converted to {"name__value": "router1"}.
                You can also use explicit filters :
                example: {"name__value": "router1", "tags__ids": ["tag1", "tag2"]}.
        partial_match: Whether to use partial matching for string filter

    Returns:
        Dictionary containing objects and metadata.

    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client

    complete_filters = {}
    if filters:
        for key, value in filters.items():
            if "__" in key:
                # TODO: How could we check if the filter is valid ?
                complete_filters[key] = value
            elif isinstance(value, list):
                complete_filters[f"{key}__values"] = value
            else:
                complete_filters[f"{key}__value"] = value

    schema = await client.schema.get(kind=kind, branch=branch)

    if complete_filters:
        nodes = await client.filters(
            kind=schema.kind,
            branch=branch,
            partial_match=partial_match,
            parallel=True,
            order=Order(disable=True),
            # populate_store=True,
            # prefetch_relationships=True,
            **complete_filters,
        )
    else:
        nodes = await client.all(
            kind=schema.kind,
            branch=branch,
            parallel=True,
            order=Order(disable=True),
            # populate_store=True,
            # prefetch_relationships=True,
        )

    # Format the response with serializable data
    serialized_nodes = []
    for node in nodes:
        node_data = await convert_node_to_dict(branch=branch, obj=node)
        serialized_nodes.append(node_data)

    # Return the serialized response
    msg = f"Retrieved {len(serialized_nodes)} nodes of kind {schema.kind}"
    print(msg)
    return {
        "success": True,
        "count": len(serialized_nodes),
        "nodes": serialized_nodes,
    }
