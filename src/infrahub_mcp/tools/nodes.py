"""Node retrieval tools for the Infrahub MCP server."""

from typing import TYPE_CHECKING, Annotated, Any

import toon
from fastmcp import Context, FastMCP
from infrahub_sdk.exceptions import GraphQLError, SchemaNotFoundError
from infrahub_sdk.schema import MainSchemaTypesAPI
from infrahub_sdk.types import Order
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.schema import get_valid_kinds_summary
from infrahub_mcp.schema_cache import get_cached_kind
from infrahub_mcp.utils import _log_and_raise_error, convert_node_to_dict, get_client

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


async def _fetch_nodes(  # noqa: PLR0913, PLR0917
    client: "InfrahubClient",
    schema: MainSchemaTypesAPI,
    branch: str | None,
    filters: dict[str, Any] | None,
    partial_match: bool,
    include_attributes: bool,
    limit: int | None,
    offset: int | None,
) -> list[Any]:
    """Fetch nodes from Infrahub, delegating offset/limit directly to the SDK."""
    kwargs: dict[str, Any] = {
        "kind": schema.kind,
        "branch": branch,
        "offset": offset,
        "limit": limit,
        "parallel": True,
        "order": Order(disable=True),
        "populate_store": True,
        "prefetch_relationships": include_attributes,
    }
    if filters:
        return await client.filters(**kwargs, partial_match=partial_match, **filters)
    return await client.all(**kwargs)


async def _get_total_count(
    client: "InfrahubClient",
    kind: str,
    branch: str | None,
    partial_match: bool,
    **filters: Any,
) -> int:
    """Return total count of matching nodes, or -1 if the count query fails.

    Delegates directly to ``client.count()`` which accepts the same filter kwargs.
    """
    try:
        return await client.count(kind=kind, branch=branch, partial_match=partial_match, **filters)
    except GraphQLError:
        return -1


async def _validate_filters(
    ctx: Context,
    schema: MainSchemaTypesAPI,
    kind: str,
    branch: str | None,
    filters: dict[str, Any],
) -> None:
    """Validate filter keys against the schema and raise an error for unknown keys.

    Args:
        ctx: MCP context for logging and error reporting.
        schema: Schema for the kind being queried.
        kind: Kind name (used in error messages).
        branch: Branch name.
        filters: Filter dict provided by the caller.

    Raises:
        RuntimeError: Via ``_log_and_raise_error`` when unknown filter keys are found.
    """
    reserved = set(filters) & _RESERVED_FILTER_KEYS
    if reserved:
        await _log_and_raise_error(
            ctx=ctx,
            error=f"Filters contain reserved key(s): {sorted(reserved)}.",
            remediation=(f"Remove reserved key(s) and check infrahub://schema/{kind} for valid filter names."),
        )

    # Build the valid filter set from the schema (same logic as schema detail)
    valid_filters: set[str] = {f"{attr.name}__value" for attr in schema.attributes}
    for rel in schema.relationships:
        try:
            rel_schema = await get_cached_kind(ctx, kind=rel.peer, branch=branch)
            valid_filters.update(f"{rel.name}__{attr.name}__value" for attr in rel_schema.attributes)
        except SchemaNotFoundError:
            continue
    invalid_keys = set(filters.keys()) - valid_filters - _RESERVED_FILTER_KEYS
    if invalid_keys:
        sorted_valid = ", ".join(sorted(valid_filters))
        await _log_and_raise_error(
            ctx=ctx,
            error=f"Invalid filter(s) for {kind}: {sorted(invalid_keys)}.",
            remediation=(
                f"Valid filters for {kind}: {sorted_valid}\nCall get_schema(kind='{kind}') for the full schema."
            ),
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
            description=(
                "Attribute/relationship filters. Keys follow the schema's "
                'filter map (e.g. {"name__value": "atl1"} or '
                '{"site__name__value": "atl1"}). See infrahub://schema/{kind} '
                "for the full filter map."
            ),
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
    offset: Annotated[
        int,
        Field(
            default=0,
            ge=0,
            description="Number of results to skip for pagination. Use with limit to page through results.",
        ),
    ] = 0,
) -> dict[str, Any]:
    """List nodes of a specific kind — the default read path for typed queries with optional filtering and pagination.

    Prefer this over ``query_graphql`` when you just need objects of one kind:
    results come back as display labels (fast, token-cheap) or full attribute
    dicts (``include_attributes=True``).

    To discover available kinds, read the ``infrahub://schema`` resource.
    If your client does not support MCP resources, call the ``get_schema`` tool instead.
    To discover available filters for a kind, read ``infrahub://schema/{kind}``
    or call ``get_schema(kind='...')``.

    Filter keys follow the schema's filter map. Attribute filters use
    ``<attr>__value`` (e.g. ``{"name__value": "atl1"}``) and relationship
    filters chain via ``<rel>__<attr>__value`` (e.g.
    ``{"site__name__value": "atl1"}``). See ``infrahub://schema/{kind}`` for
    the full list of valid keys.

    Use ``offset`` and ``limit`` to page through large result sets. The response
    always includes ``total_count`` and ``has_more`` so you know when to stop.

    Args:
        kind: Kind of the objects to retrieve.
        branch: Branch to query. Defaults to the default branch.
        filters: Dictionary of filters to apply.
        partial_match: Whether to use partial matching for string filters.
        include_attributes: Return full attribute dicts instead of display labels only.
        limit: Cap on results returned (default 50). Pass -1 for all.
        offset: Number of results to skip (default 0). Use with limit to paginate.

    Returns:
        A dict with ``nodes`` (list of display labels or TOON-encoded string),
        ``count`` (number of nodes in this page), ``total_count`` (total matching
        nodes, or ``-1`` if the count query failed), ``has_more`` (True/False
        when ``total_count`` is known, ``None`` when it is unavailable), and
        ``offset`` / ``limit`` for context.

    Raises:
        RuntimeError: Via ``_log_and_raise_error`` when the schema is not found or the query fails.
    """
    client = get_client(ctx)
    req_id = ctx.request_id
    await ctx.info(
        f"Fetching {kind} nodes: request_id={req_id!r}, branch={branch!r}, "
        f"filter_keys={sorted(filters) if filters else []}, limit={limit}, offset={offset}"
    )

    try:
        schema = await get_cached_kind(ctx, kind=kind, branch=branch)
    except SchemaNotFoundError:
        valid = await get_valid_kinds_summary(ctx, branch=branch)
        await _log_and_raise_error(
            ctx=ctx,
            error=f"Schema not found for kind: {kind}.",
            remediation=f"{valid}\nCall get_schema() for details on any kind.",
        )

    if filters:
        await _validate_filters(ctx=ctx, schema=schema, kind=kind, branch=branch, filters=filters)

    filter_kwargs = filters or {}
    total_count = await _get_total_count(client, schema.kind, branch, partial_match, **filter_kwargs)

    # Normalize limit: SDK uses None for "no limit", MCP tool uses -1
    sdk_limit = None if limit == -1 else limit
    sdk_offset = offset if offset > 0 else None

    try:
        nodes = await _fetch_nodes(
            client, schema, branch, filters, partial_match, include_attributes, sdk_limit, sdk_offset
        )
    except GraphQLError as exc:
        await _log_and_raise_error(
            ctx=ctx,
            error=exc,
            remediation=f"Check the provided filters against infrahub://schema/{kind}.",
        )

    if total_count > 0:
        await ctx.report_progress(progress=min(offset + len(nodes), total_count), total=total_count)

    # When the count query failed (total_count == -1) we cannot determine pagination
    # authoritatively — return None so clients don't mistake an exact-page-boundary
    # response for "more results available".
    has_more: bool | None = total_count > offset + len(nodes) if total_count >= 0 else None

    if include_attributes:
        dicts = [await convert_node_to_dict(obj=node, branch=branch, include_id=True) for node in nodes]
        await ctx.debug(f"Retrieved {len(dicts)} nodes of kind {kind} with attributes (request_id={req_id!r})")
        node_data: list[str] | str = toon.encode(dicts)
    else:
        node_data = [obj.display_label for obj in nodes]
        await ctx.debug(f"Retrieved {len(node_data)} nodes of kind {kind} (request_id={req_id!r})")

    return {
        "nodes": node_data,
        "count": len(nodes),
        "total_count": total_count,
        "has_more": has_more,
        "offset": offset,
        "limit": limit,
    }


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
    """Find a node of a specific kind by partial name — use when you only know part of the name.

    Matches substrings against the ``name`` attribute only (via
    ``name__value`` with ``partial_match=True``). For matching on other
    attributes, or for combining multiple filters, use ``get_nodes`` with
    an explicit ``filters`` dict instead.

    To discover available kinds, read the ``infrahub://schema`` resource.
    If your client does not support MCP resources, call the ``get_schema`` tool instead.

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
    client = get_client(ctx)
    req_id = ctx.request_id
    query = query.strip()
    if not query:
        await _log_and_raise_error(
            ctx=ctx,
            error="Search query must not be blank after stripping whitespace.",
        )
    await ctx.info(f"Searching {kind} nodes: request_id={req_id!r}, branch={branch!r}, query_len={len(query)}")

    try:
        schema = await get_cached_kind(ctx, kind=kind, branch=branch)
    except SchemaNotFoundError:
        valid = await get_valid_kinds_summary(ctx, branch=branch)
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

    results: list[str] = [obj.display_label or obj.id or "unknown" for obj in nodes[:limit]]
    await ctx.debug(f"Found {len(results)} matches in {kind}: query_len={len(query)} (request_id={req_id!r})")
    return results
