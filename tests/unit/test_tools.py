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
        assert isinstance(result.data, list)  # type: ignore[attr-defined]
        assert result.data == [  # type: ignore[attr-defined]
            "atl1",
            "den1",
            "dfw1",
            "jfk1",
            "ord1",
        ]


async def test_get_nodes_with_attributes() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("get_nodes", {"kind": "LocationSite", "include_attributes": True})
        assert isinstance(result.data, list)  # type: ignore[attr-defined]
        assert len(result.data) > 0  # type: ignore[attr-defined]
        # Each item should be a dict with attribute data
        first = result.data[0]  # type: ignore[attr-defined]
        assert isinstance(first, dict)
        assert "name" in first


async def test_search_nodes() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("search_nodes", {"query": "atl", "kind": "LocationSite"})
        assert isinstance(result.data, list)  # type: ignore[attr-defined]
        assert "atl1" in result.data  # type: ignore[attr-defined]


async def test_get_nodes_unknown_kind() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("get_nodes", {"kind": "DoesNotExist"})
        assert result.data["status"] == "error"  # type: ignore[attr-defined,index]
        assert result.data["remediation"] is not None  # type: ignore[attr-defined,index]
