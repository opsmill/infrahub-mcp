"""Node retrieval tools for the Infrahub MCP server."""

from typing import TYPE_CHECKING, Annotated, Any

import toon
from fastmcp import Context, FastMCP
from infrahub_sdk.exceptions import GraphQLError, SchemaNotFoundError
from infrahub_sdk.types import Order
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.schema import get_valid_kinds_summary
from infrahub_mcp.utils import _log_and_raise_error, convert_node_to_dict

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient

# pylint: disable=duplicate-code
mcp: FastMCP = FastMCP(name="Infrahub Nodes")

_RESERVED_FILTER_KEYS: frozenset[str] = frozenset(
    {
        "kind",
        "branch",
        "partial_match",
        "parallel",
        "order",
        "populate_store",
        "prefetch_relationships",
        "at",
        "timeout",
        "offset",
        "limit",
        "include",
        "exclude",
        "fragment",
        "property",
        "include_metadata",
    }
)


@mcp.tool(tags={"nodes", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def get_nodes(  # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals  # noqa: PLR0913, PLR0917
    ctx: Context,
    kind: Annotated[
        str,
        Field(description="Kind of the objects to retrieve. Check infrahub://schema for valid kinds."),
    ],
    branch: Annotated[
        str | None,
        Field(default=None, description="Branch to query. Defaults to the default branch."),
    ] = None,
    filters: Annotated[
        dict[str, Any] | None,
        Field(
            default=None,
            description="Attribute/relationship filters. See infrahub://schema/{kind} for the full filter map.",
        ),
    ] = None,
    partial_match: Annotated[
        bool,
        Field(default=False, description="Use partial (substring) matching for string filters."),
    ] = False,
    include_attributes: Annotated[
        bool,
        Field(
            default=False,
            description="When True, return full attribute values in "
            "TOON tabular format instead of just display labels. "
            "More expensive — omit when you only need names/counts.",
        ),
    ] = False,
    limit: Annotated[
        int,
        Field(
            default=50,
            ge=-1,
            description="Maximum nodes to return. Default 50. Pass -1 for all results (caution: may be expensive).",
        ),
    ] = 50,
) -> list[str] | str:
    """Retrieve objects of a specific kind from Infrahub.

    To discover available kinds read the resource ``infrahub://schema``.
    To discover available filters for a kind read ``infrahub://schema/{kind}``.

    Args:
        kind: Kind of the objects to retrieve.
        branch: Branch to query. Defaults to the default branch.
        filters: Dictionary of filters to apply.
        partial_match: Whether to use partial matching for string filters.
        include_attributes: Return full attribute dicts instead of display labels only.
        limit: Cap on results returned (default 50). Pass -1 for all.

    Returns:
        A list of display labels (default) or a TOON-encoded string of full attribute dicts.

    Raises:
        RuntimeError: Via ``_log_and_raise_error`` when the schema is not found or the query fails.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client  # type: ignore[union-attr]
    req_id = ctx.request_id
    await ctx.info(
        f"Fetching {kind} nodes: request_id={req_id!r}, branch={branch!r}, "
        f"filter_keys={sorted(filters) if filters else []}, limit={limit}"
    )

    try:
        schema = await client.schema.get(kind=kind, branch=branch)
    except SchemaNotFoundError:
        valid = await get_valid_kinds_summary(client, branch=branch)
        await _log_and_raise_error(
            ctx=ctx,
            error=f"Schema not found for kind: {kind}.",
            remediation=f"{valid}\nCall get_schema() for details on any kind.",
        )

    if filters:
        reserved = set(filters) & _RESERVED_FILTER_KEYS
        if reserved:
            await _log_and_raise_error(
                ctx=ctx,
                error=f"Filters contain reserved key(s): {sorted(reserved)}.",
                remediation=(f"Remove reserved key(s) and check infrahub://schema/{kind} for valid filter names."),
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
            filter_kwargs: dict[str, Any] = {**kwargs, "partial_match": partial_match, **filters}
            if limit > 0:
                filter_kwargs["limit"] = limit
            nodes = await client.filters(**filter_kwargs)
        else:
            nodes = await client.all(**kwargs)
    except GraphQLError as exc:
        await _log_and_raise_error(
            ctx=ctx,
            error=exc,
            remediation=f"Check the provided filters against infrahub://schema/{kind}.",
        )

    capped = nodes if limit == -1 else nodes[:limit]
    if include_attributes:
        dicts = [await convert_node_to_dict(obj=node, branch=branch, include_id=True) for node in capped]
        await ctx.debug(f"Retrieved {len(dicts)} nodes of kind {kind} with attributes (request_id={req_id!r})")
        return toon.encode(dicts)

    serialized = [obj.display_label for obj in capped]
    await ctx.debug(f"Retrieved {len(serialized)} nodes of kind {kind} (request_id={req_id!r})")
    return serialized


@mcp.tool(tags={"nodes", "search"}, annotations=ToolAnnotations(readOnlyHint=True))
async def search_nodes(
    ctx: Context,
    query: Annotated[
        str,
        Field(
            min_length=1,
            description="Partial name/label to search for. Matched against the 'name' attribute of each node.",
        ),
    ],
    kind: Annotated[
        str,
        Field(description="Kind to search within. Check infrahub://schema for valid kinds."),
    ],
    branch: Annotated[
        str | None,
        Field(default=None, description="Branch to query. Defaults to the default branch."),
    ] = None,
    limit: Annotated[
        int,
        Field(default=10, ge=1, le=100, description="Maximum number of results to return."),
    ] = 10,
) -> list[str]:
    """Search nodes of a specific kind by partial name match.

    A convenience wrapper around get_nodes with ``partial_match=True`` and a ``name__value``
    filter. Use when you need to find a node without knowing its exact name.

    Args:
        query: Partial name string to search for.
        kind: Kind to search within.
        branch: Branch to query.
        limit: Maximum results (1-100, default 10).

    Returns:
        A list of matching node display labels.

    Raises:
        RuntimeError: Via ``_log_and_raise_error`` when the schema is not found or the query fails.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client  # type: ignore[union-attr]
    req_id = ctx.request_id
    query = query.strip()
    if not query:
        await _log_and_raise_error(
            ctx=ctx,
            error="Search query must not be blank after stripping whitespace.",
        )
    await ctx.info(f"Searching {kind} nodes: request_id={req_id!r}, branch={branch!r}, query_len={len(query)}")

    try:
        schema = await client.schema.get(kind=kind, branch=branch)
    except SchemaNotFoundError:
        valid = await get_valid_kinds_summary(client, branch=branch)
        await _log_and_raise_error(
            ctx=ctx,
            error=f"Schema not found for kind: {kind}.",
            remediation=f"{valid}\nCall get_schema() for details on any kind.",
        )

    try:
        nodes = await client.filters(
            kind=schema.kind,
            branch=branch,
            name__value=query,
            partial_match=True,
            populate_store=True,
            order=Order(disable=True),
            limit=limit,
        )
    except GraphQLError as exc:
        await _log_and_raise_error(ctx=ctx, error=exc)

    results = [obj.display_label for obj in nodes[:limit]]
    await ctx.debug(f"Found {len(results)} matches in {kind}: query_len={len(query)} (request_id={req_id!r})")
    return results
