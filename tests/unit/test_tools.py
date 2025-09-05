from fastmcp import Client

from infrahub_mcp.server import mcp


async def test_list_schema() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("get_schema_mapping")
        assert isinstance(result.data, dict)
        assert "LocationSite" in result.data


async def test_get_node_filters(locationsite_filters: dict[str, str]) -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("get_node_filters", {"kind": "LocationSite"})
        assert isinstance(result.data, dict)
        assert result.data == locationsite_filters


async def test_get_nodes() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("get_nodes", {"kind": "LocationSite"})
        assert isinstance(result.data, list)
        assert result.data == [
            "atl1",
            "den1",
            "dfw1",
            "jfk1",
            "ord1",
        ]
