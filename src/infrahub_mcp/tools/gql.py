"""GraphQL query tool for the Infrahub MCP server."""

from typing import TYPE_CHECKING, Annotated, Any

from fastmcp import Context, FastMCP
from infrahub_sdk.exceptions import GraphQLError
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.utils import _log_and_raise_error

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClient

mcp: FastMCP = FastMCP(name="Infrahub GraphQL")


@mcp.tool(tags={"schemas", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def get_graphql_schema(
    ctx: Context,
    branch: Annotated[
        str | None,
        Field(default=None, description="Get the graphql schema in a specific branch"),
    ],
                             ) -> MCPResponse:
    """Retrieve the GraphQL schema from Infrahub

    Parameters:
        branch: Get the graphql schema in a specific branch, Defaults to None (uses default branch).

    Returns:
        MCPResponse with the GraphQL schema as a string.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client
    resp = await client._get(url=f"{client.address}/schema.graphql?branch={branch}")  # noqa: SLF001
    return MCPResponse(status=MCPToolStatus.SUCCESS, data=resp.text)


@mcp.tool(tags={"schemas", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=False))
async def query_graphql(
    ctx: Context,
    query: Annotated[str, Field(description="GraphQL query to execute.")],
    branch: Annotated[
        str | None,
        Field(
            default=None,
            description="Branch to execute the query against. Defaults to None (uses default branch).",
        ),
    ] = None,
) -> dict[str, Any]:
    """Execute a GraphQL query against Infrahub.

    To discover available kinds and their attributes, read the ``infrahub://schema``
    resource. If your client does not support MCP resources, call the ``get_schema``
    tool instead. For the full GraphQL SDL, read ``infrahub://graphql-schema``.

    Parameters:
        query: GraphQL query to execute.
        branch: Branch to execute the query against. Defaults to None (uses default branch).

    Returns:
        The result of the query.

    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client  # type: ignore[union-attr]
    try:
        data = await client.execute_graphql(query=query, branch_name=branch)
    except GraphQLError as exc:
        await _log_and_raise_error(
            ctx,
            exc,
            remediation=(
                "Call get_schema() to list valid kinds, or "
                "get_schema(kind='...') to see attributes and filters."
            ),
        )

    return data
