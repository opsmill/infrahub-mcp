"""Tests for single-level schema peer expansion."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from infrahub_sdk.exceptions import SchemaNotFoundError

from infrahub_mcp.schema import get_schema_detail


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


def _patch_cached_kind(schemas: dict[str, MagicMock]) -> Any:
    """Patch the schema-cache lookup ``get_schema_detail`` uses to resolve kinds.

    ``get_schema_detail`` takes a FastMCP ``Context`` and resolves kinds through
    the hash-validated schema cache. These tests cover peer-expansion *shaping*
    only, so the cache lookup is stubbed rather than exercised.
    """

    def _get_cached_kind(ctx: Any, *, kind: str, branch: str | None = None) -> MagicMock:
        if kind not in schemas:
            raise SchemaNotFoundError(kind)
        return schemas[kind]

    return patch("infrahub_mcp.schema.get_cached_kind", new=AsyncMock(side_effect=_get_cached_kind))


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
    with _patch_cached_kind({"KindA": schema_a}):
        result = await get_schema_detail(MagicMock(), kind="KindA", expand_peers=True)
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
