"""Graph-traversal tools for the Infrahub MCP server (requires Infrahub 1.10+)."""

from typing import Annotated

import toon
from fastmcp import Context, FastMCP
from infrahub_sdk.exceptions import VersionNotSupportedError
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.traversal import NodeResolutionError, run_find_paths, run_find_reachable
from infrahub_mcp.utils import _log_and_raise_error, get_client

mcp: FastMCP = FastMCP(name="Infrahub Traversal")

_VERSION_REMEDIATION = "Graph traversal requires Infrahub 1.10 or later (infrahub-sdk >= 1.22)."
_RESOLUTION_REMEDIATION = "Use get_nodes or search_nodes to obtain a valid node id or kind-qualified HFID."


async def _find_paths_impl(  # noqa: PLR0913, PLR0917
    ctx: Context,
    source: str,
    destination: str,
    branch: str | None,
    max_depth: int | None,
    kind_filter: list[str] | None,
    relationship_filter: list[str] | None,
) -> str:
    """Resolve endpoints, run the path traversal, and translate failures to ToolError."""
    client = get_client(ctx)
    try:
        result = await run_find_paths(
            client,
            source=source,
            destination=destination,
            branch=branch,
            max_depth=max_depth,
            kind_filter=kind_filter,
            relationship_filter=relationship_filter,
        )
    except VersionNotSupportedError as exc:
        await _log_and_raise_error(ctx=ctx, error=str(exc), remediation=_VERSION_REMEDIATION)
    except NodeResolutionError as exc:
        await _log_and_raise_error(ctx=ctx, error=str(exc), remediation=_RESOLUTION_REMEDIATION)
    return toon.encode(result)


async def _find_reachable_impl(  # noqa: PLR0913, PLR0917
    ctx: Context,
    source: str,
    target_kinds: list[str],
    branch: str | None,
    max_depth: int | None,
    max_results: int,
    shortest_paths_only: bool,
) -> str:
    """Resolve the source, run the reachability traversal, and translate failures to ToolError."""
    client = get_client(ctx)
    try:
        result = await run_find_reachable(
            client,
            source=source,
            target_kinds=target_kinds,
            branch=branch,
            max_depth=max_depth,
            max_results=max_results,
            shortest_paths_only=shortest_paths_only,
        )
    except VersionNotSupportedError as exc:
        await _log_and_raise_error(ctx=ctx, error=str(exc), remediation=_VERSION_REMEDIATION)
    except NodeResolutionError as exc:
        await _log_and_raise_error(ctx=ctx, error=str(exc), remediation=_RESOLUTION_REMEDIATION)
    return toon.encode(result)


@mcp.tool(tags={"traversal", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def find_paths(  # noqa: PLR0913, PLR0917
    ctx: Context,
    source: Annotated[
        str,
        Field(description="Start node: a UUID or kind-qualified HFID (e.g. 'InfraDevice__atl1-edge1')."),
    ],
    destination: Annotated[str, Field(description="End node: a UUID or kind-qualified HFID.")],
    branch: Annotated[
        str | None,
        Field(default=None, description="Branch to query. Defaults to the default branch."),
    ] = None,
    max_depth: Annotated[
        int | None,
        Field(default=None, description="Maximum relationship hops to explore."),
    ] = None,
    kind_filter: Annotated[
        list[str] | None,
        Field(default=None, description="Only traverse through nodes of these kinds."),
    ] = None,
    relationship_filter: Annotated[
        list[str] | None,
        Field(
            default=None, description="Only follow these schema relationship identifiers (e.g. 'device__interface')."
        ),
    ] = None,
) -> str:
    """Find the shortest path(s) between two nodes in the Infrahub graph.

    Use this to answer "how are these two objects connected?". A result with
    ``count`` of 0 means no path exists within ``max_depth``. Requires Infrahub 1.10+.

    Args:
        source: Start node — UUID or kind-qualified HFID.
        destination: End node — UUID or kind-qualified HFID.
        branch: Branch to query. Defaults to the default branch.
        max_depth: Maximum relationship hops to explore.
        kind_filter: Only traverse through nodes of these kinds.
        relationship_filter: Only follow these schema relationship identifiers.

    Returns:
        TOON-encoded dict: source, destination, count, and paths (each a list of hops).
    """
    return await _find_paths_impl(ctx, source, destination, branch, max_depth, kind_filter, relationship_filter)


@mcp.tool(tags={"traversal", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def find_reachable(  # noqa: PLR0913, PLR0917
    ctx: Context,
    source: Annotated[str, Field(description="Source node: a UUID or kind-qualified HFID.")],
    target_kinds: Annotated[
        list[str],
        Field(description="Node kinds to search for, reachable from the source."),
    ],
    branch: Annotated[
        str | None,
        Field(default=None, description="Branch to query. Defaults to the default branch."),
    ] = None,
    max_depth: Annotated[
        int | None,
        Field(default=None, description="Maximum traversal depth."),
    ] = None,
    max_results: Annotated[
        int,
        Field(default=20, description="Maximum distinct reachable nodes to return."),
    ] = 20,
    shortest_paths_only: Annotated[
        bool,
        Field(default=True, description="Return only the shortest path to each target."),
    ] = True,
) -> str:
    """Find nodes of the given kinds reachable from a source node (impact analysis).

    Use this to answer "what depends on / is connected to this object?" — for
    blast-radius and dependency discovery. Requires Infrahub 1.10+.

    Args:
        source: Source node — UUID or kind-qualified HFID.
        target_kinds: Node kinds to search for.
        branch: Branch to query. Defaults to the default branch.
        max_depth: Maximum traversal depth.
        max_results: Maximum distinct reachable nodes to return.
        shortest_paths_only: Return only the shortest path to each target.

    Returns:
        TOON-encoded dict: source, count, and dependencies (each with depth, node, and path).
    """
    return await _find_reachable_impl(ctx, source, target_kinds, branch, max_depth, max_results, shortest_paths_only)
