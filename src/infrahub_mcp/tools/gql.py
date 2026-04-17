"""GraphQL query tool for the Infrahub MCP server (read-only)."""

from typing import TYPE_CHECKING, Annotated, Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from graphql import OperationType
from graphql import parse as gql_parse
from graphql.error import GraphQLSyntaxError
from infrahub_sdk.exceptions import GraphQLError
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.utils import _log_and_raise_error

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClient

mcp: FastMCP = FastMCP(name="Infrahub GraphQL")


@mcp.tool(tags={"graphql", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def query_graphql(
    ctx: Context,
    query: Annotated[
        str, Field(description="GraphQL query string. Only queries are allowed — use mutate_graphql for mutations.")
    ],
    branch: Annotated[
        str | None,
        Field(
            default=None,
            description="Branch to execute the query against. Defaults to None (uses default branch).",
        ),
    ] = None,
) -> dict[str, Any]:
    """Execute a read-only GraphQL query against Infrahub.

    This tool only accepts GraphQL **queries**. For mutations, use the
    ``mutate_graphql`` tool instead (available when write mode is enabled).

    To discover available kinds and their attributes, read the ``infrahub://schema``
    resource. If your client does not support MCP resources, call the ``get_schema``
    tool instead. For the full GraphQL SDL, read ``infrahub://graphql-schema``.

    Parameters:
        query: GraphQL query to execute (mutations are rejected).
        branch: Branch to execute the query against. Defaults to None (uses default branch).

    Returns:
        The result of the query.
    """
    try:
        document = gql_parse(query)
    except GraphQLSyntaxError as exc:
        msg = f"Invalid GraphQL syntax: {exc}"
        raise ToolError(msg) from exc

    for definition in document.definitions:
        if hasattr(definition, "operation") and definition.operation == OperationType.MUTATION:
            msg = "Mutations are not allowed in query_graphql. Use mutate_graphql instead."
            raise ToolError(msg)

    client: InfrahubClient = ctx.request_context.lifespan_context.client  # type: ignore[union-attr]
    try:
        data = await client.execute_graphql(query=query, branch_name=branch)
    except GraphQLError as exc:
        await _log_and_raise_error(
            ctx,
            exc,
            remediation=(
                "Call get_schema() to list valid kinds, or get_schema(kind='...') to see attributes and filters."
            ),
        )

    return data
