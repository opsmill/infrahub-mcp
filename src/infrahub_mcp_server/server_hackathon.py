# server.py
import sys

from fastmcp import FastMCP
from infrahub_sdk import InfrahubClient
from infrahub_sdk.exceptions import GraphQLError, SchemaNotFoundError
from infrahub_sdk.types import Order

from .utils import convert_node_to_dict

mcp = FastMCP("Demo 🚀")


@mcp.tool()
def add(a: int, b: int) -> int:
    """Add two numbers"""
    return a + b


@mcp.tool()
async def infrahub_query_graphql(
    *,
    query: str,
) -> dict:
    """Execute a GraphQL query against Infrahub.

    Args:
        query: GraphQL query to execute.
        at: Time when the query should be executed. Defaults to None.
        infrahub_url: URL of the Infrahub instance. Defaults to None (uses environment variable).
        infrahub_api_token: API token for Infrahub. Defaults to None (uses environment variable).

    Returns:
        Dictionary containing the result of the GraphQL query.

    """
    try:
        client = InfrahubClient()
        return {"success": True, "data": await client.execute_graphql(query=query)}
    except Exception as exc:  # noqa: BLE001
        print(exc)
        sys.exit(1)


@mcp.tool()
async def infrahub_get_graphql_schema() -> dict:
    """Retrieve the GraphQL schema from Infrahub"""
    client = InfrahubClient()
    resp = await client._get(url=f"{client.address}/schema.graphql")  # noqa: SLF001
    return {"data": resp.text}


@mcp.tool()
async def infrahub_get_nodes(
    *,
    kind: str,
    branch: str | None = None,
    filters: dict | None = None,
    partial_match: bool = False,
) -> dict:
    """Retrieve objects from Infrahub.

    Args:
        infrahub_client: Infrahub client to use
        kind: Kind of the objects to retrieve.
        branch: Branch to retrieve the objects from. Defaults to None (uses default branch).
        filters: Dictionary of filters to apply. Simple filters like {"name": "router1"} will be
                automatically converted to {"name__value": "router1"}.
                You can also use explicit filters :
                example: {"name__value": "router1", "tags__ids": ["tag1", "tag2"]}.
        partial_match: Whether to use partial matching for string filter
        infrahub_url: URL of the Infrahub instance. Defaults to None (uses environment variable).
        infrahub_api_token: API token for Infrahub. Defaults to None (uses environment variable).

    Returns:
        Dictionary containing objects and metadata.

    """
    client = InfrahubClient()

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

    try:
        schema = await client.schema.get(kind=kind, branch=branch)
    except SchemaNotFoundError:
        print("Schema not found")
        sys.exit(1)

    try:
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
    except GraphQLError:
        print("GraphQLError")
        sys.exit(1)

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


if __name__ == "__main__":
    mcp.run()
    # mcp.run(transport="streamable-http", host="127.0.0.1", port=8001, path="/mcp")
