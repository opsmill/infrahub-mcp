"""Tests for single-level schema peer expansion."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock, patch

from infrahub_sdk.exceptions import SchemaNotFoundError

from infrahub_mcp.schema import get_schema_detail

if TYPE_CHECKING:
    from collections.abc import Iterator


def _make_attribute(name: str, kind: str = "Text", optional: bool = False) -> MagicMock:
    attr = MagicMock()
    attr.name = name
    attr.kind = kind
    attr.optional = optional
    return attr


def _make_relationship(name: str, peer: str, cardinality: str = "many", optional: bool = False) -> MagicMock:
    rel = MagicMock()
    rel.name = name
    rel.peer = peer
    rel.cardinality = cardinality
    rel.optional = optional
    return rel


def _make_schema_node(
    kind: str, label: str, namespace: str, attributes: list[Any], relationships: list[Any]
) -> MagicMock:
    node = MagicMock()
    node.kind = kind
    node.label = label
    node.namespace = namespace
    node.attributes = attributes
    node.relationships = relationships
    return node


@contextlib.contextmanager
def _patch_cached_kind(schemas: dict[str, MagicMock]) -> Iterator[tuple[AsyncMock, AsyncMock, MagicMock]]:
    """Stub the schema-cache reads and the client resolution ``get_schema_detail`` uses.

    ``get_schema_detail`` takes a FastMCP ``Context``, resolves one client for
    the call, reads the requested kind through the hash-validated schema cache
    and resolves that kind's relationship peers from a single branch-schema
    read — only peers absent from it fall back to ``get_cached_kind``. These
    tests cover peer-expansion *shaping* only, so all three are stubbed rather
    than exercised. Yields the ``get_cached_kind`` stub, the
    ``get_cached_branch_schema`` stub and the ``get_client`` stub for tests
    that assert how the call reads and threads its client.
    """

    def _get_cached_kind(ctx: Any, *, kind: str, branch: str | None = None, client: Any = None) -> MagicMock:
        if kind not in schemas:
            raise SchemaNotFoundError(kind)
        return schemas[kind]

    branch_schema = MagicMock(name="branch-schema")
    branch_schema.nodes = schemas
    cached_kind = AsyncMock(side_effect=_get_cached_kind)
    branch_read = AsyncMock(return_value=branch_schema)
    with (
        patch("infrahub_mcp.schema.get_cached_kind", new=cached_kind),
        patch("infrahub_mcp.schema.get_cached_branch_schema", new=branch_read),
        patch("infrahub_mcp.utils.get_client", return_value=MagicMock(name="resolved-client")) as get_client,
    ):
        yield cached_kind, branch_read, get_client


def _schemas_a_b() -> dict[str, MagicMock]:
    schema_a = _make_schema_node(
        kind="KindA",
        label="Kind A",
        namespace="Test",
        attributes=[_make_attribute("name")],
        relationships=[_make_relationship("children", "KindB")],
    )
    schema_b = _make_schema_node(
        kind="KindB",
        label="Kind B",
        namespace="Test",
        attributes=[_make_attribute("label")],
        relationships=[_make_relationship("parent", "KindA")],
    )
    return {"KindA": schema_a, "KindB": schema_b}


async def test_no_peer_schema_when_disabled() -> None:
    with _patch_cached_kind(_schemas_a_b()):
        result = await get_schema_detail(MagicMock(), kind="KindA", expand_peers=False)
    assert result["kind"] == "KindA"
    assert "filters" in result
    for rel in result["relationships"]:
        assert "peer_schema" not in rel


async def test_peer_schema_present_when_enabled() -> None:
    with _patch_cached_kind(_schemas_a_b()):
        result = await get_schema_detail(MagicMock(), kind="KindA", expand_peers=True)
    children = next(r for r in result["relationships"] if r["name"] == "children")
    assert children["peer_schema"]["kind"] == "KindB"
    assert "attributes" in children["peer_schema"]
    assert "relationships" in children["peer_schema"]
    assert "filters" not in children["peer_schema"]


async def test_peer_schema_relationships_not_expanded() -> None:
    with _patch_cached_kind(_schemas_a_b()):
        result = await get_schema_detail(MagicMock(), kind="KindA", expand_peers=True)
    children = next(r for r in result["relationships"] if r["name"] == "children")
    for rel in children["peer_schema"]["relationships"]:
        assert "peer_schema" not in rel


async def test_self_referential_kind_expands_one_level() -> None:
    schema_a = _make_schema_node(
        kind="KindA",
        label="Kind A",
        namespace="Test",
        attributes=[_make_attribute("name")],
        relationships=[_make_relationship("parent", "KindA")],
    )
    with _patch_cached_kind({"KindA": schema_a}):
        result = await get_schema_detail(MagicMock(), kind="KindA", expand_peers=True)
    parent = next(r for r in result["relationships"] if r["name"] == "parent")
    assert parent["peer_schema"]["kind"] == "KindA"
    for rel in parent["peer_schema"]["relationships"]:
        assert "peer_schema" not in rel


async def test_missing_peer_kind_skipped() -> None:
    schema_a = _make_schema_node(
        kind="KindA",
        label="Kind A",
        namespace="Test",
        attributes=[_make_attribute("name")],
        relationships=[_make_relationship("broken", "NonExistent")],
    )
    with _patch_cached_kind({"KindA": schema_a}) as (cached_kind, _branch_read, _get_client):
        result = await get_schema_detail(MagicMock(), kind="KindA", expand_peers=True)
    # A peer absent from the branch-schema read still falls back to
    # get_cached_kind, whose forced revalidation catches a kind added upstream.
    assert [call.kwargs["kind"] for call in cached_kind.await_args_list] == ["KindA", "NonExistent"]
    broken = next(r for r in result["relationships"] if r["name"] == "broken")
    assert broken["peer"] == "NonExistent"
    assert broken["cardinality"] == "many"
    assert broken["optional"] is False
    assert "peer_schema" not in broken


async def test_filters_include_peer_attributes() -> None:
    with _patch_cached_kind(_schemas_a_b()):
        result = await get_schema_detail(MagicMock(), kind="KindA", expand_peers=True)
    filters = {f["filter"] for f in result["filters"]}
    assert "name__value" in filters
    assert "children__label__value" in filters


async def test_kind_detail_with_peers_resolves_one_client_and_threads_it() -> None:
    """One credential check per request: the kind and its peers are read on the same client.

    In the passthrough modes each unprimed client probes Infrahub with the
    caller's credential, so a detail read that resolved a client per helper
    call would probe once per peer.
    """
    with _patch_cached_kind(_schemas_a_b()) as (cached_kind, branch_read, get_client):
        await get_schema_detail(MagicMock(), kind="KindA", expand_peers=True)

    get_client.assert_called_once()
    branch_read.assert_awaited_once()
    # KindA itself; its peer KindB comes from that one branch-schema read.
    assert cached_kind.await_count == 1
    assert all(call.kwargs["client"] is get_client.return_value for call in cached_kind.await_args_list)
    assert branch_read.await_args_list[0].kwargs["client"] is get_client.return_value


async def test_kind_detail_uses_the_callers_client_and_resolves_none() -> None:
    caller = MagicMock(name="callers-client")
    with _patch_cached_kind(_schemas_a_b()) as (cached_kind, branch_read, get_client):
        await get_schema_detail(MagicMock(), kind="KindA", expand_peers=True, client=caller)

    get_client.assert_not_called()
    branch_read.assert_awaited_once()
    assert cached_kind.await_count == 1
    assert all(call.kwargs["client"] is caller for call in cached_kind.await_args_list)
    assert branch_read.await_args_list[0].kwargs["client"] is caller
