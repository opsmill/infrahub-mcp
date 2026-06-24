"""Tests for single-level schema peer expansion."""

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
    result = await get_schema_detail(_make_client(_schemas_a_b()), kind="KindA", expand_peers=False)
    assert result["kind"] == "KindA"
    assert "filters" in result
    for rel in result["relationships"]:
        assert "peer_schema" not in rel


async def test_peer_schema_present_when_enabled() -> None:
    result = await get_schema_detail(_make_client(_schemas_a_b()), kind="KindA", expand_peers=True)
    children = next(r for r in result["relationships"] if r["name"] == "children")
    assert children["peer_schema"]["kind"] == "KindB"
    assert "attributes" in children["peer_schema"]
    assert "relationships" in children["peer_schema"]
    assert "filters" not in children["peer_schema"]


async def test_peer_schema_relationships_not_expanded() -> None:
    result = await get_schema_detail(_make_client(_schemas_a_b()), kind="KindA", expand_peers=True)
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
    result = await get_schema_detail(_make_client({"KindA": schema_a}), kind="KindA", expand_peers=True)
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
    result = await get_schema_detail(_make_client({"KindA": schema_a}), kind="KindA", expand_peers=True)
    broken = next(r for r in result["relationships"] if r["name"] == "broken")
    assert broken["peer"] == "NonExistent"
    assert broken["cardinality"] == "many"
    assert broken["optional"] is False
    assert "peer_schema" not in broken


async def test_filters_include_peer_attributes() -> None:
    result = await get_schema_detail(_make_client(_schemas_a_b()), kind="KindA", expand_peers=True)
    filters = {f["filter"] for f in result["filters"]}
    assert "name__value" in filters
    assert "children__label__value" in filters
