import json

import toon
from fastmcp import Client

from infrahub_mcp.server import mcp


async def test_schema_catalog_resource() -> None:
    async with Client(mcp) as client:
        resources = await client.read_resource("infrahub://schema")
        assert len(resources) > 0
        data = json.loads(resources[0].text)  # type: ignore[attr-defined]
        assert isinstance(data, dict)
        assert "LocationSite" in data


async def test_schema_kind_resource() -> None:
    async with Client(mcp) as client:
        resources = await client.read_resource("infrahub://schema/LocationSite")
        assert len(resources) > 0
        data = toon.decode(resources[0].text)  # type: ignore[attr-defined]
        assert data["kind"] == "LocationSite"
        assert "attributes" in data
        assert "filters" in data
        # Filters for known attributes should be present
        assert any(d.get("filter") == "name__value" for d in data["filters"])


async def test_branches_resource() -> None:
    async with Client(mcp) as client:
        resources = await client.read_resource("infrahub://branches")
        assert len(resources) > 0
        data = json.loads(resources[0].text)  # type: ignore[attr-defined]
        assert isinstance(data, dict)
        # Default Infrahub instances always have a main branch
        assert "main" in data


async def test_get_nodes() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("get_nodes", {"kind": "LocationSite"})
        assert result.is_error is False
        assert isinstance(result.data, list)
        assert sorted(result.data) == [
            "atl1",
            "den1",
            "dfw1",
            "jfk1",
            "ord1",
        ]


async def test_get_nodes_with_attributes() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("get_nodes", {"kind": "LocationSite", "include_attributes": True})
        assert result.is_error is False
        # Data is TOON-encoded when include_attributes is True
        assert isinstance(result.data, str)
        decoded = toon.decode(result.data)
        assert isinstance(decoded, list)
        assert len(decoded) > 0
        first = decoded[0]
        assert isinstance(first, dict)
        assert "name" in first


async def test_search_nodes() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("search_nodes", {"query": "atl", "kind": "LocationSite"})
        assert result.is_error is False
        assert isinstance(result.data, list)
        assert "atl1" in result.data


async def test_get_nodes_unknown_kind() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("get_nodes", {"kind": "DoesNotExist"}, raise_on_error=False)
        assert result.is_error is True
        text = result.content[0].text  # type: ignore[union-attr]
        assert "Remediation:" in text


async def test_get_schema_tool_catalog() -> None:
    """get_schema with no kind returns the same catalog as the resource."""
    async with Client(mcp) as client:
        result = await client.call_tool("get_schema", {})
        assert result.is_error is False
        data = json.loads(result.data)
        assert isinstance(data, dict)
        assert "LocationSite" in data
        # Internal kinds should be filtered out
        for key in data:
            assert not key.startswith(("Internal", "Profile", "Template"))


async def test_get_schema_tool_kind_detail() -> None:
    """get_schema with a kind returns the same detail as the resource."""
    async with Client(mcp) as client:
        result = await client.call_tool("get_schema", {"kind": "LocationSite"})
        assert result.is_error is False
        data = toon.decode(result.data)
        assert data["kind"] == "LocationSite"
        assert "attributes" in data
        assert "relationships" in data
        assert "filters" in data
        assert any(d.get("filter") == "name__value" for d in data["filters"])


async def test_get_schema_tool_invalid_kind() -> None:
    """get_schema with invalid kind returns error with valid kinds list."""
    async with Client(mcp) as client:
        result = await client.call_tool("get_schema", {"kind": "DoesNotExist"}, raise_on_error=False)
        assert result.is_error is True
        text = result.content[0].text  # type: ignore[union-attr]
        assert "DoesNotExist" in text
        assert "Valid kinds:" in text
        assert "get_schema()" in text


async def test_get_schema_tool_matches_resource() -> None:
    """get_schema tool output matches infrahub://schema resource output."""
    async with Client(mcp) as client:
        # Compare catalog
        resource = await client.read_resource("infrahub://schema")
        resource_data = json.loads(resource[0].text)  # type: ignore[attr-defined]
        tool_result = await client.call_tool("get_schema", {})
        tool_data = json.loads(tool_result.data)
        assert resource_data == tool_data
