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


@mcp.tool(tags={"graphql", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=False))
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
