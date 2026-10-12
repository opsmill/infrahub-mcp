"""GraphQL query tool for the Infrahub MCP server (read-only)."""

from typing import Annotated, Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from graphql import DocumentNode, FieldNode, OperationDefinitionNode, OperationType
from graphql import parse as gql_parse
from graphql.error import GraphQLSyntaxError
from infrahub_sdk.exceptions import GraphQLError
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.utils import _log_and_raise_error, get_client

mcp: FastMCP = FastMCP(name="Infrahub GraphQL")

_SCHEMA_REMEDIATION = "Call get_schema() to list valid kinds, or get_schema(kind='...') to see attributes and filters."
_FILTERS_ARGUMENT_ERROR = "Unknown argument 'filters'"
_EXAMPLE_KIND = "DcimDevice"


def _first_kind(document: DocumentNode) -> str:
    """Return the first top-level field of the first operation, or an example kind when there is none."""
    for definition in document.definitions:
        if isinstance(definition, OperationDefinitionNode):
            for selection in definition.selection_set.selections:
                if isinstance(selection, FieldNode) and not selection.name.value.startswith("__"):
                    return selection.name.value
    return _EXAMPLE_KIND


def _remediation(exc: GraphQLError, document: DocumentNode) -> str:
    """Name the mistake when Infrahub rejects a ``filters`` argument; otherwise point to the schema."""
    if not any(_FILTERS_ARGUMENT_ERROR in str(error.get("message", "")) for error in exc.errors):
        return _SCHEMA_REMEDIATION
    kind = _first_kind(document)
    return (
        'Infrahub GraphQL has no "filters" argument. Put the filter keys directly on the kind\'s query, '
        f'for example:\n  {kind}(name__value: "atl1") {{ count edges {{ node {{ id }} }} }}\n'
        f'The keys are the ones get_schema(kind="{kind}") lists under "filters"; '
        "in get_nodes the same keys go in the filters argument."
    )


@mcp.tool(tags={"graphql", "retrieve"}, annotations=ToolAnnotations(read_only_hint=True))
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
    """Execute a read-only GraphQL query against Infrahub — use for reads only, never mutations.

    Mutations are rejected at the AST level: use ``mutate_graphql`` instead
    (available when write mode is enabled). For simple attribute reads, prefer
    ``get_nodes`` / ``search_nodes`` — use GraphQL only when you need relationship
    traversal, aggregation, or fields not exposed by the typed tools.

    Call ``get_schema()`` for the available kinds and ``get_schema(kind='...')``
    for a kind's attributes, relationships and filter keys; never guess them.

    Filter keys go directly on the kind's query as arguments;
    there is no "filters" argument. Example::

        LocationSite(name__value: "atl1") { count edges { node { id name { value } } } }

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

    client = get_client(ctx)
    try:
        data = await client.execute_graphql(query=query, branch_name=branch)
    except GraphQLError as exc:
        await _log_and_raise_error(
            ctx,
            exc,
            remediation=_remediation(exc, document),
        )

    return data
