"""Core graph-traversal logic for the Infrahub MCP server.

Wraps the SDK's traverse_paths / reachable_nodes (Infrahub 1.10+) and shapes
their results into compact dicts for MCP tool responses. Kept separate from the
thin tool wrappers in tools/traversal.py so this logic is unit-testable without
a live server.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, cast

from infrahub_sdk.exceptions import NodeNotFoundError

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient
    from infrahub_sdk.graph_traversal import (
        Path,
        PathHop,
        PathNode,
        PathTraversalResult,
        ReachableNodesResult,
    )
    from infrahub_sdk.node import InfrahubNode

# Matches infrahub_sdk's get_human_friendly_id_as_string(include_kind=True) output.
_HFID_SEPARATOR = "__"
_MIN_HFID_PARTS = 2


class NodeResolutionError(Exception):
    """Raised when a source/destination reference cannot be resolved to a node."""


def _is_uuid(value: str) -> bool:
    """Return True if value parses as a UUID (an Infrahub node id)."""
    try:
        uuid.UUID(value)
    except ValueError:
        return False
    return True


async def resolve_node_ref(
    client: InfrahubClient,
    ref: str,
    *,
    branch: str | None = None,
) -> str | InfrahubNode:
    """Resolve a node reference (UUID or kind-qualified HFID) for traversal.

    A UUID is returned unchanged (the SDK accepts a UUID string directly).
    Otherwise the value is treated as a kind-qualified HFID of the form
    ``Kind__part1__part2`` (the form get_nodes emits) and resolved via the SDK.

    Args:
        client: Infrahub SDK client.
        ref: A node UUID or a kind-qualified HFID.
        branch: Optional branch to resolve against.

    Returns:
        The UUID string, or the resolved InfrahubNode.

    Raises:
        NodeResolutionError: If the value is malformed or no node matches.
    """
    if _is_uuid(ref):
        return ref
    parts = ref.split(_HFID_SEPARATOR)
    if len(parts) < _MIN_HFID_PARTS:
        msg = f"'{ref}' is neither a UUID nor a kind-qualified HFID (expected 'Kind__id')."
        raise NodeResolutionError(msg)
    kind, hfid = parts[0], parts[1:]
    try:
        return await client.get(kind=kind, hfid=hfid, branch=branch)
    except NodeNotFoundError as exc:
        msg = f"Could not resolve '{ref}': {exc}"
        raise NodeResolutionError(msg) from exc


def _shape_node(node: PathNode) -> dict[str, Any]:
    """Full node identity for endpoints and dependency targets."""
    return {"id": node.id, "kind": node.kind, "display_label": node.display_label, "hfid": node.hfid}


def _shape_hop(hop: PathHop) -> dict[str, Any]:
    """Compact per-hop shape: peer identity plus the relationship name used."""
    out: dict[str, Any] = {"node": {"kind": hop.node.kind, "display_label": hop.node.display_label}}
    if hop.relationship is not None:
        out["relationship"] = hop.relationship.from_label
    return out


def _shape_path(path: Path) -> dict[str, Any]:
    return {"depth": path.depth, "hops": [_shape_hop(h) for h in path.hops]}


def shape_path_result(result: PathTraversalResult) -> dict[str, Any]:
    """Shape a PathTraversalResult into a compact, TOON-friendly dict."""
    return {
        "source": _shape_node(result.source),
        "destination": _shape_node(result.destination),
        "count": result.count,
        "paths": [_shape_path(p) for p in result.paths],
    }


def shape_reachable_result(result: ReachableNodesResult) -> dict[str, Any]:
    """Shape a ReachableNodesResult into a compact, TOON-friendly dict."""
    return {
        "source": _shape_node(result.source),
        "count": result.count,
        "dependencies": [
            {"depth": dep.depth, "node": _shape_node(dep.node), "path": _shape_path(dep.path)}
            for dep in result.dependencies
        ],
    }


async def run_find_paths(  # noqa: PLR0913
    client: InfrahubClient,
    *,
    source: str,
    destination: str,
    branch: str | None = None,
    max_depth: int | None = None,
    kind_filter: list[str] | None = None,
    relationship_filter: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve endpoints and find shortest path(s) between two nodes."""
    src = await resolve_node_ref(client, source, branch=branch)
    dst = await resolve_node_ref(client, destination, branch=branch)
    result = await client.traverse_paths(
        src,
        dst,
        max_depth=max_depth,
        # agent passes kind-name strings; the SDK's kind-filter list type is invariant, so cast to widen.
        kind_filter=cast("list[Any] | None", kind_filter),
        relationship_filter=relationship_filter,
        branch=branch,
    )
    return shape_path_result(result)


async def run_find_reachable(  # noqa: PLR0913
    client: InfrahubClient,
    *,
    source: str,
    target_kinds: list[str],
    branch: str | None = None,
    max_depth: int | None = None,
    max_results: int = 20,
    shortest_paths_only: bool = True,
) -> dict[str, Any]:
    """Resolve the source and find reachable nodes of the given kinds."""
    src = await resolve_node_ref(client, source, branch=branch)
    result = await client.reachable_nodes(
        src,
        cast("list[Any]", target_kinds),
        max_depth=max_depth,
        max_results=max_results,
        shortest_paths_only=shortest_paths_only,
        branch=branch,
    )
    return shape_reachable_result(result)
