from typing import TYPE_CHECKING

from fastmcp import Context, FastMCP

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClient

mcp: FastMCP = FastMCP(name="Infrahub GraphQL")


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
