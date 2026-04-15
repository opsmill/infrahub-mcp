"""Tests for the analytics report fetchers module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from infrahub_mcp.reports.fetchers import (
    compute_field_distributions,
    compute_relationship_distributions,
    fetch_node_counts,
    fetch_nodes_for_kind,
    fetch_schema_catalog,
    fetch_schema_detail,
)


# ---------------------------------------------------------------------------
# Helpers — mock schema objects mirroring the Infrahub SDK structure
# ---------------------------------------------------------------------------


@dataclass
class _MockAttr:
    """Minimal attribute descriptor matching the SDK schema structure."""

    name: str
    kind: str
    optional: bool = False


@dataclass
class _MockRel:
    """Minimal relationship descriptor matching the SDK schema structure."""

    name: str
    peer: str
    cardinality: str = "one"
    optional: bool = False


@dataclass
class _MockSchema:
    """Minimal schema object matching the SDK schema structure."""

    kind: str
    namespace: str
    label: str
    attributes: list[_MockAttr] = field(default_factory=list)
    relationships: list[_MockRel] = field(default_factory=list)


def _make_client(
    schema_all: dict[str, _MockSchema] | None = None,
    schema_get: _MockSchema | None = None,
    nodes: list[Any] | None = None,
    count: int = 0,
) -> MagicMock:
    """Build a lightweight InfrahubClient mock."""
    client = MagicMock()
    client.schema = MagicMock()
    client.schema.all = AsyncMock(return_value=schema_all or {})
    client.schema.get = AsyncMock(return_value=schema_get)
    client.all = AsyncMock(return_value=nodes or [])
    client.count = AsyncMock(return_value=count)
    return client


# ---------------------------------------------------------------------------
# Tests — fetch_schema_catalog
# ---------------------------------------------------------------------------


class TestFetchSchemaCatalog:
    async def test_returns_correct_shape(self) -> None:
        schemas = {
            "InfraDevice": _MockSchema(
                kind="InfraDevice",
                namespace="Infra",
                label="Device",
                attributes=[_MockAttr("name", "Text"), _MockAttr("status", "Dropdown")],
                relationships=[_MockRel("site", "LocationSite")],
            ),
            "LocationSite": _MockSchema(
                kind="LocationSite",
                namespace="Location",
                label="Site",
                attributes=[_MockAttr("name", "Text")],
                relationships=[],
            ),
        }
        client = _make_client(schema_all=schemas)
        result = await fetch_schema_catalog(client)

        assert len(result) == 2
        device = next(r for r in result if r["kind"] == "InfraDevice")
        assert device["namespace"] == "Infra"
        assert device["label"] == "Device"
        assert device["attr_count"] == 2
        assert device["rel_count"] == 1

    async def test_empty_schema_returns_empty_list(self) -> None:
        client = _make_client(schema_all={})
        result = await fetch_schema_catalog(client)
        assert result == []

    async def test_uses_kind_as_label_when_label_is_none(self) -> None:
        schemas = {
            "WidgetFoo": _MockSchema(
                kind="WidgetFoo",
                namespace="Widget",
                label="",  # empty label → fall back to kind
                attributes=[],
                relationships=[],
            ),
        }
        client = _make_client(schema_all=schemas)
        result = await fetch_schema_catalog(client)
        assert result[0]["label"] == "WidgetFoo"

    async def test_passes_branch_to_sdk(self) -> None:
        client = _make_client(schema_all={})
        await fetch_schema_catalog(client, branch="my-branch")
        client.schema.all.assert_awaited_once_with(branch="my-branch")


# ---------------------------------------------------------------------------
# Tests — fetch_schema_detail
# ---------------------------------------------------------------------------


class TestFetchSchemaDetail:
    async def test_returns_kind_attributes_relationships(self) -> None:
        schema = _MockSchema(
            kind="InfraDevice",
            namespace="Infra",
            label="Device",
            attributes=[
                _MockAttr("name", "Text", optional=False),
                _MockAttr("status", "Dropdown", optional=True),
            ],
            relationships=[
                _MockRel("site", "LocationSite", cardinality="one"),
                _MockRel("interfaces", "InfraInterface", cardinality="many"),
            ],
        )
        client = _make_client(schema_get=schema)
        result = await fetch_schema_detail(client, "InfraDevice")

        assert result["kind"] == "InfraDevice"
        assert len(result["attributes"]) == 2
        assert result["attributes"][0] == {"name": "name", "kind": "Text", "optional": False}
        assert result["attributes"][1] == {"name": "status", "kind": "Dropdown", "optional": True}
        assert len(result["relationships"]) == 2
        assert result["relationships"][0] == {"name": "site", "peer": "LocationSite", "cardinality": "one"}

    async def test_empty_attributes_and_relationships(self) -> None:
        schema = _MockSchema(kind="EmptyKind", namespace="X", label="Empty")
        client = _make_client(schema_get=schema)
        result = await fetch_schema_detail(client, "EmptyKind")
        assert result["attributes"] == []
        assert result["relationships"] == []

    async def test_passes_kind_and_branch_to_sdk(self) -> None:
        schema = _MockSchema(kind="InfraDevice", namespace="Infra", label="Device")
        client = _make_client(schema_get=schema)
        await fetch_schema_detail(client, "InfraDevice", branch="test-branch")
        client.schema.get.assert_awaited_once_with(kind="InfraDevice", branch="test-branch")


# ---------------------------------------------------------------------------
# Tests — fetch_nodes_for_kind
# ---------------------------------------------------------------------------


class TestFetchNodesForKind:
    async def test_returns_rows_and_column_names(self) -> None:
        schema = _MockSchema(
            kind="InfraDevice",
            namespace="Infra",
            label="Device",
            attributes=[_MockAttr("name", "Text"), _MockAttr("status", "Dropdown")],
            relationships=[_MockRel("site", "LocationSite")],
        )
        mock_node = MagicMock()
        client = _make_client(schema_get=schema, nodes=[mock_node])

        expected_dict = {"name": "router1", "status": "active", "site": "atl1"}
        with patch("infrahub_mcp.reports.fetchers.convert_node_to_dict", new=AsyncMock(return_value=expected_dict)):
            rows, columns = await fetch_nodes_for_kind(client, "InfraDevice")

        assert columns == ["name", "status", "site"]
        assert rows == [expected_dict]

    async def test_empty_nodes_returns_empty_rows(self) -> None:
        schema = _MockSchema(
            kind="InfraDevice",
            namespace="Infra",
            label="Device",
            attributes=[_MockAttr("name", "Text")],
            relationships=[],
        )
        client = _make_client(schema_get=schema, nodes=[])
        with patch("infrahub_mcp.reports.fetchers.convert_node_to_dict", new=AsyncMock(return_value={})):
            rows, columns = await fetch_nodes_for_kind(client, "InfraDevice")

        assert rows == []
        assert columns == ["name"]

    async def test_limit_passed_to_client_all(self) -> None:
        schema = _MockSchema(kind="X", namespace="N", label="X")
        client = _make_client(schema_get=schema, nodes=[])
        with patch("infrahub_mcp.reports.fetchers.convert_node_to_dict", new=AsyncMock(return_value={})):
            await fetch_nodes_for_kind(client, "X", limit=50)
        client.all.assert_awaited_once_with(kind="X", branch=None, limit=50)

    async def test_branch_passed_to_schema_and_all(self) -> None:
        schema = _MockSchema(kind="X", namespace="N", label="X")
        client = _make_client(schema_get=schema, nodes=[])
        with patch("infrahub_mcp.reports.fetchers.convert_node_to_dict", new=AsyncMock(return_value={})):
            await fetch_nodes_for_kind(client, "X", branch="dev")
        client.schema.get.assert_awaited_once_with(kind="X", branch="dev")
        client.all.assert_awaited_once_with(kind="X", branch="dev", limit=200)


# ---------------------------------------------------------------------------
# Tests — fetch_node_counts
# ---------------------------------------------------------------------------


class TestFetchNodeCounts:
    async def test_counts_returned_sorted_descending(self) -> None:
        schemas: dict[str, _MockSchema] = {
            "InfraDevice": _MockSchema(kind="InfraDevice", namespace="Infra", label="Device"),
            "LocationSite": _MockSchema(kind="LocationSite", namespace="Location", label="Site"),
            "InfraInterface": _MockSchema(kind="InfraInterface", namespace="Infra", label="Interface"),
        }
        client = _make_client(schema_all=schemas)

        # Return different counts depending on kind
        async def _count(kind: str, branch: str | None = None) -> int:
            return {"InfraDevice": 5, "LocationSite": 10, "InfraInterface": 3}[kind]

        client.count = _count

        result = await fetch_node_counts(client, ["InfraDevice", "LocationSite", "InfraInterface"])

        assert [r["kind"] for r in result] == ["LocationSite", "InfraDevice", "InfraInterface"]
        assert [r["count"] for r in result] == [10, 5, 3]

    async def test_label_from_schema_catalog(self) -> None:
        schemas: dict[str, _MockSchema] = {
            "InfraDevice": _MockSchema(kind="InfraDevice", namespace="Infra", label="My Device"),
        }
        client = _make_client(schema_all=schemas)
        client.count = AsyncMock(return_value=7)

        result = await fetch_node_counts(client, ["InfraDevice"])
        assert result[0]["label"] == "My Device"

    async def test_on_progress_callback_called_with_done_total(self) -> None:
        schemas: dict[str, _MockSchema] = {
            "A": _MockSchema(kind="A", namespace="N", label="A"),
            "B": _MockSchema(kind="B", namespace="N", label="B"),
            "C": _MockSchema(kind="C", namespace="N", label="C"),
        }
        client = _make_client(schema_all=schemas)
        client.count = AsyncMock(return_value=1)

        calls: list[tuple[int, int]] = []

        async def _on_progress(done: int, total: int) -> None:
            calls.append((done, total))

        await fetch_node_counts(client, ["A", "B", "C"], on_progress=_on_progress)

        assert len(calls) == 3
        # Each call should have total=3 and done increasing
        totals = [t for _, t in calls]
        assert all(t == 3 for t in totals)
        dones = sorted(d for d, _ in calls)
        assert dones == [1, 2, 3]

    async def test_empty_kinds_returns_empty_list(self) -> None:
        client = _make_client(schema_all={})
        result = await fetch_node_counts(client, [])
        assert result == []

    async def test_missing_kind_in_schema_uses_kind_as_label(self) -> None:
        """If a kind is not in the schema catalog, fall back to using kind as label."""
        schemas: dict[str, _MockSchema] = {}
        client = _make_client(schema_all=schemas)
        client.count = AsyncMock(return_value=0)

        result = await fetch_node_counts(client, ["UnknownKind"])
        assert result[0]["label"] == "UnknownKind"


# ---------------------------------------------------------------------------
# Tests — compute_field_distributions
# ---------------------------------------------------------------------------


class TestComputeFieldDistributions:
    def test_dropdown_attribute_included(self) -> None:
        nodes = [
            {"status": "active"},
            {"status": "active"},
            {"status": "inactive"},
        ]
        attributes = [{"name": "status", "kind": "Dropdown"}]
        result = compute_field_distributions(nodes, attributes)

        assert len(result) == 1
        assert result[0]["field"] == "status"
        dist = {d["value"]: d["count"] for d in result[0]["distribution"]}
        assert dist["active"] == 2
        assert dist["inactive"] == 1

    def test_attribute_with_more_than_10_distinct_values_excluded(self) -> None:
        # 11 distinct values → should be excluded
        nodes = [{f"name": f"node{i}"} for i in range(11)]
        attributes = [{"name": "name", "kind": "Text"}]
        result = compute_field_distributions(nodes, attributes)
        assert result == []

    def test_attribute_with_10_or_fewer_distinct_values_included(self) -> None:
        nodes = [{"role": f"role{i % 5}"} for i in range(20)]
        attributes = [{"name": "role", "kind": "Text"}]
        result = compute_field_distributions(nodes, attributes)
        assert len(result) == 1
        assert result[0]["field"] == "role"

    def test_empty_nodes_returns_empty_list(self) -> None:
        attributes = [{"name": "status", "kind": "Dropdown"}]
        result = compute_field_distributions([], attributes)
        assert result == []

    def test_empty_attributes_returns_empty_list(self) -> None:
        nodes = [{"name": "x"}]
        result = compute_field_distributions(nodes, [])
        assert result == []

    def test_distribution_sorted_by_count_descending(self) -> None:
        nodes = [
            {"status": "active"},
            {"status": "active"},
            {"status": "active"},
            {"status": "inactive"},
            {"status": "inactive"},
            {"status": "decommissioned"},
        ]
        attributes = [{"name": "status", "kind": "Dropdown"}]
        result = compute_field_distributions(nodes, attributes)
        counts = [d["count"] for d in result[0]["distribution"]]
        assert counts == sorted(counts, reverse=True)

    def test_missing_field_in_node_treated_as_empty_string(self) -> None:
        nodes = [{"status": "active"}, {}]  # second node lacks "status"
        attributes = [{"name": "status", "kind": "Dropdown"}]
        result = compute_field_distributions(nodes, attributes)
        assert len(result) == 1
        values = {d["value"] for d in result[0]["distribution"]}
        assert "" in values  # missing field treated as ""


# ---------------------------------------------------------------------------
# Tests — compute_relationship_distributions
# ---------------------------------------------------------------------------


class TestComputeRelationshipDistributions:
    def test_one_cardinality_counts_distinct_peers(self) -> None:
        nodes = [
            {"site": "atl1"},
            {"site": "atl1"},
            {"site": "den1"},
        ]
        relationships = [{"name": "site", "cardinality": "one"}]
        result = compute_relationship_distributions(nodes, relationships)

        assert len(result) == 1
        assert result[0]["field"] == "site"
        dist = {d["value"]: d["count"] for d in result[0]["distribution"]}
        assert dist["atl1"] == 2
        assert dist["den1"] == 1

    def test_many_cardinality_flattens_and_counts(self) -> None:
        nodes = [
            {"tags": ["red", "green"]},
            {"tags": ["red", "blue"]},
            {"tags": ["green"]},
        ]
        relationships = [{"name": "tags", "cardinality": "many"}]
        result = compute_relationship_distributions(nodes, relationships)

        assert len(result) == 1
        dist = {d["value"]: d["count"] for d in result[0]["distribution"]}
        assert dist["red"] == 2
        assert dist["green"] == 2
        assert dist["blue"] == 1

    def test_empty_nodes_returns_empty_list(self) -> None:
        relationships = [{"name": "site", "cardinality": "one"}]
        result = compute_relationship_distributions([], relationships)
        assert result == []

    def test_empty_relationships_returns_empty_list(self) -> None:
        nodes = [{"site": "atl1"}]
        result = compute_relationship_distributions(nodes, [])
        assert result == []

    def test_none_values_skipped(self) -> None:
        nodes = [
            {"site": "atl1"},
            {"site": None},
            {"site": "atl1"},
        ]
        relationships = [{"name": "site", "cardinality": "one"}]
        result = compute_relationship_distributions(nodes, relationships)
        dist = {d["value"]: d["count"] for d in result[0]["distribution"]}
        assert dist["atl1"] == 2
        assert "None" not in dist

    def test_mixed_cardinality_in_many_rel_non_list_value(self) -> None:
        """If a 'many' relationship unexpectedly holds a scalar, treat it as single value."""
        nodes = [
            {"tags": ["red"]},
            {"tags": "blue"},  # scalar, not a list
        ]
        relationships = [{"name": "tags", "cardinality": "many"}]
        result = compute_relationship_distributions(nodes, relationships)
        dist = {d["value"]: d["count"] for d in result[0]["distribution"]}
        assert dist["red"] == 1
        assert dist["blue"] == 1

    def test_field_absent_in_all_nodes_excluded_from_result(self) -> None:
        nodes = [{"name": "x"}, {"name": "y"}]
        relationships = [{"name": "tags", "cardinality": "many"}]
        result = compute_relationship_distributions(nodes, relationships)
        assert result == []
