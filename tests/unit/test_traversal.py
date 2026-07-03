"""Tests for graph-traversal core logic (node resolution, shaping, orchestration)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
import toon
from fastmcp.exceptions import ToolError
from infrahub_sdk.exceptions import (
    GraphQLError,
    NodeNotFoundError,
    SchemaNotFoundError,
    VersionNotSupportedError,
)
from infrahub_sdk.graph_traversal import (
    Path,
    PathHop,
    PathNode,
    PathRelationship,
    PathTraversalResult,
    ReachableNode,
    ReachableNodesResult,
)

from infrahub_mcp.config import ServerConfig
from infrahub_mcp.tools.traversal import _find_paths_impl, _find_reachable_impl
from infrahub_mcp.traversal import (
    NodeResolutionError,
    resolve_node_ref,
    run_find_paths,
    run_find_reachable,
    shape_path_result,
    shape_reachable_result,
)
from infrahub_mcp.utils import AppContext

UUID_A = "1891a122-8875-bae7-3866-10658751d7cc"
UUID_B = "1891a12b-27e5-fe3e-386c-1065983045b0"


def _node(node_id: str, kind: str, label: str) -> PathNode:
    return PathNode(id=node_id, kind=kind, label=kind, display_label=label, hfid=[label])


# --- resolve_node_ref ------------------------------------------------------


async def test_resolve_uuid_passthrough() -> None:
    client = AsyncMock()
    result = await resolve_node_ref(client, UUID_A)
    assert result == UUID_A
    client.get.assert_not_called()


async def test_resolve_hfid_calls_get() -> None:
    client = AsyncMock()
    sentinel = object()
    client.get = AsyncMock(return_value=sentinel)
    result = await resolve_node_ref(client, "InfraDevice__atl1-edge1", branch="main")
    assert result is sentinel
    client.get.assert_awaited_once_with(kind="InfraDevice", hfid=["atl1-edge1"], branch="main")


async def test_resolve_multi_component_hfid() -> None:
    client = AsyncMock()
    client.get = AsyncMock(return_value=object())
    await resolve_node_ref(client, "LocationRack__site1__rack-7")
    client.get.assert_awaited_once_with(kind="LocationRack", hfid=["site1", "rack-7"], branch=None)


async def test_resolve_malformed_raises() -> None:
    client = AsyncMock()
    with pytest.raises(NodeResolutionError, match="kind-qualified HFID"):
        await resolve_node_ref(client, "noseparator")


async def test_resolve_not_found_raises() -> None:
    client = AsyncMock()
    client.get = AsyncMock(side_effect=NodeNotFoundError(identifier={"kind": ["InfraDevice"]}, message="not found"))
    with pytest.raises(NodeResolutionError, match="Could not resolve"):
        await resolve_node_ref(client, "InfraDevice__ghost")


@pytest.mark.parametrize(
    "exc",
    [
        SchemaNotFoundError("UnknownKind"),
        ValueError("Cannot filter by HFID if the node doesn't have an HFID defined"),
        IndexError("More than 1 node returned"),
    ],
)
async def test_resolve_get_failures_become_node_resolution_error(exc: Exception) -> None:
    client = AsyncMock()
    client.get = AsyncMock(side_effect=exc)
    with pytest.raises(NodeResolutionError, match="Could not resolve"):
        await resolve_node_ref(client, "SomeKind__some-id")


async def test_resolve_non_canonical_uuid_not_treated_as_uuid() -> None:
    # uuid.UUID() accepts 32-hex-no-dashes, but it is not a canonical node id, so it must
    # fall through to HFID parsing (and, lacking '__', be reported as malformed).
    client = AsyncMock()
    with pytest.raises(NodeResolutionError, match="kind-qualified HFID"):
        await resolve_node_ref(client, "12345678901234567890123456789012")
    client.get.assert_not_called()


# --- shaping ---------------------------------------------------------------


def test_shape_path_result() -> None:
    result = PathTraversalResult(
        source=_node(UUID_A, "InfraDevice", "edge1"),
        destination=_node(UUID_B, "InfraDevice", "edge2"),
        count=1,
        paths=[
            Path(
                depth=2,
                hops=[
                    PathHop(node=_node(UUID_A, "InfraDevice", "edge1")),
                    PathHop(
                        node=_node("x", "InfraInterfaceL3", "Ethernet1"),
                        relationship=PathRelationship(
                            from_rel="interfaces",
                            from_label="interfaces",
                            to_rel="device",
                            to_label="device",
                            kind="InfraInterface",
                        ),
                    ),
                ],
            )
        ],
    )
    shaped = shape_path_result(result)
    assert shaped["count"] == 1
    assert shaped["source"] == {"id": UUID_A, "kind": "InfraDevice", "display_label": "edge1", "hfid": ["edge1"]}
    assert shaped["paths"][0]["depth"] == 2
    first_hop, second_hop = shaped["paths"][0]["hops"]
    assert first_hop == {"node": {"kind": "InfraDevice", "display_label": "edge1"}}
    assert second_hop["node"] == {"kind": "InfraInterfaceL3", "display_label": "Ethernet1"}
    assert second_hop["relationship"] == "interfaces"


def test_shape_reachable_result() -> None:
    result = ReachableNodesResult(
        source=_node(UUID_A, "InfraDevice", "edge1"),
        count=1,
        dependencies=[
            ReachableNode(
                depth=1,
                node=_node("c", "InfraCircuit", "DUFF-1"),
                path=Path(depth=1, hops=[PathHop(node=_node("c", "InfraCircuit", "DUFF-1"))]),
            )
        ],
    )
    shaped = shape_reachable_result(result)
    assert shaped["count"] == 1
    dep = shaped["dependencies"][0]
    assert dep["depth"] == 1
    assert dep["node"] == {"id": "c", "kind": "InfraCircuit", "display_label": "DUFF-1", "hfid": ["DUFF-1"]}
    assert dep["path"]["depth"] == 1


# --- orchestrators ---------------------------------------------------------


async def test_run_find_paths_resolves_and_calls_sdk() -> None:
    client = AsyncMock()
    client.traverse_paths = AsyncMock(
        return_value=PathTraversalResult(
            source=_node(UUID_A, "InfraDevice", "edge1"),
            destination=_node(UUID_B, "InfraDevice", "edge2"),
            count=0,
            paths=[],
        )
    )
    shaped = await run_find_paths(client, source=UUID_A, destination=UUID_B, max_depth=4)
    assert shaped["count"] == 0
    client.traverse_paths.assert_awaited_once_with(
        UUID_A, UUID_B, max_depth=4, kind_filter=None, relationship_filter=None, branch=None
    )


async def test_run_find_paths_version_error_propagates() -> None:
    client = AsyncMock()
    client.traverse_paths = AsyncMock(side_effect=VersionNotSupportedError("Graph path traversal", "1.10"))
    with pytest.raises(VersionNotSupportedError):
        await run_find_paths(client, source=UUID_A, destination=UUID_B)


async def test_run_find_reachable_default_max_results() -> None:
    client = AsyncMock()
    client.reachable_nodes = AsyncMock(
        return_value=ReachableNodesResult(source=_node(UUID_A, "InfraDevice", "edge1"), count=0, dependencies=[])
    )
    await run_find_reachable(client, source=UUID_A, target_kinds=["InfraCircuit"])
    client.reachable_nodes.assert_awaited_once_with(
        UUID_A, ["InfraCircuit"], max_depth=None, max_results=20, shortest_paths_only=True, branch=None
    )


# --- tool wrappers ---------------------------------------------------------


def _make_ctx(client: AsyncMock) -> MagicMock:
    ctx = MagicMock()
    ctx.request_context.lifespan_context = AppContext(client=client, config=ServerConfig())
    ctx.error = AsyncMock()
    ctx.info = AsyncMock()
    return ctx


async def test_find_paths_impl_happy_returns_toon() -> None:
    client = AsyncMock()
    client.traverse_paths = AsyncMock(
        return_value=PathTraversalResult(
            source=_node(UUID_A, "InfraDevice", "edge1"),
            destination=_node(UUID_B, "InfraDevice", "edge2"),
            count=0,
            paths=[],
        )
    )
    out = await _find_paths_impl(_make_ctx(client), UUID_A, UUID_B, None, None, None, None)
    assert toon.decode(out)["count"] == 0


async def test_find_paths_impl_version_error_raises_toolerror() -> None:
    client = AsyncMock()
    client.traverse_paths = AsyncMock(side_effect=VersionNotSupportedError("Graph path traversal", "1.10"))
    with pytest.raises(ToolError, match=r"1\.10"):
        await _find_paths_impl(_make_ctx(client), UUID_A, UUID_B, None, None, None, None)


async def test_find_paths_impl_resolution_error_raises_toolerror() -> None:
    client = AsyncMock()
    with pytest.raises(ToolError, match="get_nodes"):
        await _find_paths_impl(_make_ctx(client), "bad-ref", UUID_B, None, None, None, None)


async def test_find_paths_impl_graphql_error_raises_toolerror() -> None:
    client = AsyncMock()
    client.traverse_paths = AsyncMock(side_effect=GraphQLError([{"message": "node not found"}]))
    with pytest.raises(ToolError, match="get_nodes"):
        await _find_paths_impl(_make_ctx(client), UUID_A, UUID_B, None, None, None, None)


async def test_find_reachable_impl_resolution_error_raises_toolerror() -> None:
    client = AsyncMock()
    with pytest.raises(ToolError, match="get_nodes"):
        await _find_reachable_impl(_make_ctx(client), "bad-ref", ["InfraCircuit"], None, None, 20, True)
