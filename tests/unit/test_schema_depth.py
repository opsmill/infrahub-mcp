"""Tests for recursive schema depth expansion."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

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


def _make_client(schemas: dict[str, MagicMock]) -> AsyncMock:
    client = AsyncMock()

    def _get_schema(kind: str, branch: str | None = None) -> MagicMock:  # noqa: ARG001
        if kind not in schemas:
            raise SchemaNotFoundError(kind)
        return schemas[kind]

    client.schema.get = AsyncMock(side_effect=_get_schema)
    return client


async def test_no_peer_schema_at_depth_zero() -> None:
    """Depth 0 should produce the same output as before (no peer_schema)."""
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
        relationships=[],
    )
    client = _make_client({"KindA": schema_a, "KindB": schema_b})

    result = await get_schema_detail(client, kind="KindA", depth=0)

    assert result["kind"] == "KindA"
    for rel in result["relationships"]:
        assert "peer_schema" not in rel
        assert "_seen" not in rel


async def test_peer_schema_present_at_depth_one() -> None:
    """Depth 1 should include peer_schema on relationships."""
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
    client = _make_client({"KindA": schema_a, "KindB": schema_b})

    result = await get_schema_detail(client, kind="KindA", depth=1)

    children_rel = next(r for r in result["relationships"] if r["name"] == "children")
    assert "peer_schema" in children_rel
    assert children_rel["peer_schema"]["kind"] == "KindB"
    assert "attributes" in children_rel["peer_schema"]
    assert "relationships" in children_rel["peer_schema"]
    assert "filters" not in children_rel["peer_schema"]


async def test_peer_schema_relationships_have_no_nested_peer_schema() -> None:
    """At depth 1, relationships inside peer_schema should not have peer_schema."""
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
    client = _make_client({"KindA": schema_a, "KindB": schema_b})

    result = await get_schema_detail(client, kind="KindA", depth=1)

    children_rel = next(r for r in result["relationships"] if r["name"] == "children")
    peer_rels = children_rel["peer_schema"]["relationships"]
    for rel in peer_rels:
        assert "peer_schema" not in rel


async def test_two_level_nesting() -> None:
    """Depth 2 should nest two levels deep."""
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
        relationships=[_make_relationship("items", "KindC")],
    )
    schema_c = _make_schema_node(
        kind="KindC",
        label="Kind C",
        namespace="Test",
        attributes=[_make_attribute("value")],
        relationships=[],
    )
    client = _make_client({"KindA": schema_a, "KindB": schema_b, "KindC": schema_c})

    result = await get_schema_detail(client, kind="KindA", depth=2)

    children_rel = next(r for r in result["relationships"] if r["name"] == "children")
    assert children_rel["peer_schema"]["kind"] == "KindB"

    items_rel = next(r for r in children_rel["peer_schema"]["relationships"] if r["name"] == "items")
    assert "peer_schema" in items_rel
    assert items_rel["peer_schema"]["kind"] == "KindC"


async def test_self_referential_kind() -> None:
    """A kind that points to itself should be detected as a cycle."""
    schema_a = _make_schema_node(
        kind="KindA",
        label="Kind A",
        namespace="Test",
        attributes=[_make_attribute("name")],
        relationships=[_make_relationship("parent", "KindA")],
    )
    client = _make_client({"KindA": schema_a})

    result = await get_schema_detail(client, kind="KindA", depth=2)

    parent_rel = next(r for r in result["relationships"] if r["name"] == "parent")
    assert parent_rel.get("_seen") is True
    assert "peer_schema" not in parent_rel


async def test_mutual_cycle() -> None:
    """A <-> B cycle should be detected and marked with _seen."""
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
    client = _make_client({"KindA": schema_a, "KindB": schema_b})

    result = await get_schema_detail(client, kind="KindA", depth=3)

    children_rel = next(r for r in result["relationships"] if r["name"] == "children")
    assert "peer_schema" in children_rel

    parent_rel = next(r for r in children_rel["peer_schema"]["relationships"] if r["name"] == "parent")
    assert parent_rel.get("_seen") is True
    assert "peer_schema" not in parent_rel


async def test_same_kind_deduped_across_branches() -> None:
    """KindC appears via two paths — first is inlined, second is @ref."""
    schema_a = _make_schema_node(
        kind="KindA",
        label="Kind A",
        namespace="Test",
        attributes=[_make_attribute("name")],
        relationships=[
            _make_relationship("left", "KindB"),
            _make_relationship("right", "KindC"),
        ],
    )
    schema_b = _make_schema_node(
        kind="KindB",
        label="Kind B",
        namespace="Test",
        attributes=[_make_attribute("label")],
        relationships=[_make_relationship("target", "KindC")],
    )
    schema_c = _make_schema_node(
        kind="KindC",
        label="Kind C",
        namespace="Test",
        attributes=[_make_attribute("value")],
        relationships=[],
    )
    client = _make_client({"KindA": schema_a, "KindB": schema_b, "KindC": schema_c})

    result = await get_schema_detail(client, kind="KindA", depth=2)

    # One of the two paths gets the full inline, the other gets @ref
    right_rel = next(r for r in result["relationships"] if r["name"] == "right")
    left_rel = next(r for r in result["relationships"] if r["name"] == "left")
    target_rel = next(r for r in left_rel["peer_schema"]["relationships"] if r["name"] == "target")

    # Collect both peer_schema values for KindC
    kindc_refs = [right_rel["peer_schema"], target_rel["peer_schema"]]
    inline_count = sum(1 for r in kindc_refs if isinstance(r, dict))
    ref_count = sum(1 for r in kindc_refs if r == "@ref:KindC")
    assert inline_count == 1
    assert ref_count == 1


async def test_missing_peer_kind_skipped() -> None:
    """When a relationship references a non-existent peer kind, it is kept but without peer_schema."""
    schema_a = _make_schema_node(
        kind="KindA",
        label="Kind A",
        namespace="Test",
        attributes=[_make_attribute("name")],
        relationships=[_make_relationship("broken", "NonExistent")],
    )
    client = _make_client({"KindA": schema_a})

    result = await get_schema_detail(client, kind="KindA", depth=1)

    broken_rel = next(r for r in result["relationships"] if r["name"] == "broken")
    assert broken_rel["peer"] == "NonExistent"
    assert broken_rel["cardinality"] == "many"
    assert broken_rel["optional"] is False
    assert "peer_schema" not in broken_rel
    assert "_seen" not in broken_rel


async def test_negative_depth_treated_as_zero() -> None:
    """Negative depth should be normalized to 0."""
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
        relationships=[],
    )
    client = _make_client({"KindA": schema_a, "KindB": schema_b})

    result = await get_schema_detail(client, kind="KindA", depth=-1)

    for rel in result["relationships"]:
        assert "peer_schema" not in rel
        assert "_seen" not in rel
