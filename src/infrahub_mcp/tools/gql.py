from typing import TYPE_CHECKING, Annotated, Any

from fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.utils import MCPResponse, MCPToolStatus

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClient

mcp: FastMCP = FastMCP(name="Infrahub GraphQL")


@mcp.tool(tags={"schemas", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def get_graphql_schema(ctx: Context) -> MCPResponse:
    """Retrieve the GraphQL schema from Infrahub

    Parameters:
        None

    Returns:
        MCPResponse with the GraphQL schema as a string.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client
    resp = await client._get(url=f"{client.address}/schema.graphql")  # noqa: SLF001
    return MCPResponse(status=MCPToolStatus.SUCCESS, data=resp.text)


@mcp.tool(tags={"schemas", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=False))
async def query_graphql(
    ctx: Context,
    query: Annotated[str, Field(description="GraphQL query to execute.")],
    branch: Annotated[
        str | None,
        Field(default=None, description="Branch to execute the query against. Defaults to None (uses default branch)."),
    ],
) -> MCPResponse[dict[str, Any]]:
    """Execute a GraphQL query against Infrahub.

    Parameters:
        query: GraphQL query to execute.
        branch: Branch to execute the query against. Defaults to None (uses default branch).

    Returns:
        MCPResponse with the result of the query.

    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client
    data = await client.execute_graphql(query=query, branch_name=branch)

    return MCPResponse(status=MCPToolStatus.SUCCESS, data=data)
