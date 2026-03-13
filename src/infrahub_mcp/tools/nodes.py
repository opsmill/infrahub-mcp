from typing import TYPE_CHECKING, Annotated, Any

from fastmcp import Context, FastMCP
from infrahub_sdk.exceptions import GraphQLError, SchemaNotFoundError
from infrahub_sdk.types import Order
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.utils import MCPResponse, MCPToolStatus, _log_and_return_error, convert_node_to_dict

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient

mcp: FastMCP = FastMCP(name="Infrahub Nodes")


@mcp.tool(tags={"nodes", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def get_nodes(  # noqa: PLR0913, PLR0917
    ctx: Context,
    kind: Annotated[str, Field(description="Kind of the objects to retrieve. Check infrahub://schema for valid kinds.")],
    branch: Annotated[
        str | None,
        Field(default=None, description="Branch to query. Defaults to the default branch."),
    ],
    filters: Annotated[
        dict[str, Any] | None,
        Field(
            default=None,
            description="Attribute/relationship filters. See infrahub://schema/{kind} for the full filter map.",
        ),
    ],
    partial_match: Annotated[
        bool, Field(default=False, description="Use partial (substring) matching for string filters.")
    ],
    include_attributes: Annotated[
        bool,
        Field(
            default=False,
            description="When True, return full attribute values instead of just display labels. "
            "More expensive — omit when you only need names/counts.",
        ),
    ],
) -> MCPResponse:
    """Retrieve objects of a specific kind from Infrahub.

    To discover available kinds read the resource ``infrahub://schema``.
    To discover available filters for a kind read ``infrahub://schema/{kind}``.

    Parameters:
        kind: Kind of the objects to retrieve.
        branch: Branch to query. Defaults to the default branch.
        filters: Dictionary of filters to apply.
        partial_match: Whether to use partial matching for string filters.
        include_attributes: Return full attribute dict instead of display labels only.

    Returns:
        MCPResponse with a list of display labels (default) or full attribute dicts.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client  # type: ignore[assignment]
    await ctx.info(f"Fetching nodes of kind: {kind} with filters: {filters}")

    try:
        schema = await client.schema.get(kind=kind, branch=branch)
    except SchemaNotFoundError:
        return await _log_and_return_error(
            ctx=ctx,
            error=f"Schema not found for kind: {kind}.",
            remediation="Read infrahub://schema to list available kinds.",
        )

    try:
        kwargs: dict[str, Any] = {
            "kind": schema.kind,
            "branch": branch,
            "parallel": True,
            "order": Order(disable=True),
            "populate_store": True,
            "prefetch_relationships": include_attributes,
        }
        if filters:
            nodes = await client.filters(**kwargs, partial_match=partial_match, **filters)
        else:
            nodes = await client.all(**kwargs)
    except GraphQLError as exc:
        return await _log_and_return_error(
            ctx=ctx, error=exc, remediation=f"Check the provided filters against infrahub://schema/{kind}."
        )

    if include_attributes:
        serialized = [await convert_node_to_dict(obj=node, branch=branch) for node in nodes]
    else:
        serialized = [obj.display_label for obj in nodes]

    await ctx.debug(f"Retrieved {len(serialized)} nodes of kind {kind}")
    return MCPResponse(status=MCPToolStatus.SUCCESS, data=serialized)


@mcp.tool(tags={"nodes", "search"}, annotations=ToolAnnotations(readOnlyHint=True))
async def search_nodes(
    ctx: Context,
    query: Annotated[
        str,
        Field(description="Partial name/label to search for. Matched against the 'name' attribute of each node."),
    ],
    kind: Annotated[str, Field(description="Kind to search within. Check infrahub://schema for valid kinds.")],
    branch: Annotated[
        str | None,
        Field(default=None, description="Branch to query. Defaults to the default branch."),
    ],
    limit: Annotated[int, Field(default=10, ge=1, le=100, description="Maximum number of results to return.")] = 10,
) -> MCPResponse:
    """Search nodes of a specific kind by partial name match.

    A convenience wrapper around get_nodes with ``partial_match=True`` and a ``name__value``
    filter. Use when you need to find a node without knowing its exact name.

    Parameters:
        query: Partial name string to search for.
        kind: Kind to search within.
        branch: Branch to query.
        limit: Maximum results (1-100, default 10).

    Returns:
        MCPResponse with a list of matching node display labels.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client  # type: ignore[assignment]
    await ctx.info(f"Searching nodes of kind {kind} matching '{query}'")

    try:
        schema = await client.schema.get(kind=kind, branch=branch)
    except SchemaNotFoundError:
        return await _log_and_return_error(
            ctx=ctx,
            error=f"Schema not found for kind: {kind}.",
            remediation="Read infrahub://schema to list available kinds.",
        )

    try:
        nodes = await client.filters(
            kind=schema.kind,
            branch=branch,
            name__value=query,
            partial_match=True,
            populate_store=True,
            order=Order(disable=True),
        )
    except GraphQLError as exc:
        return await _log_and_return_error(ctx=ctx, error=exc)

    results = [obj.display_label for obj in nodes[:limit]]
    await ctx.debug(f"Found {len(results)} matches for '{query}' in {kind}")
    return MCPResponse(status=MCPToolStatus.SUCCESS, data=results)
