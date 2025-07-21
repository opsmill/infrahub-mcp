
from fastmcp import  Client

from infrahub_mcp_server.server import mcp


async def test_list_schema():
    async with Client(mcp) as client:
        result = await client.call_tool("get_schema_mapping")
        assert isinstance(result.data, dict)
        assert "LocationSite" in result.data

async def test_get_node_filters():
    async with Client(mcp) as client:
        result = await client.call_tool("get_node_filters", {"kind": "LocationSite"})
        assert isinstance(result.data, dict)
        assert result.data == {
            'address__value': 'String',
            'city__value': 'String',
            'contact__value': 'String',
            'description__value': 'String',
            'name__value': 'String',
        }


async def test_get_objects():
    async with Client(mcp) as client:
        result = await client.call_tool("get_objects", {"kind": "LocationSite"})
        assert isinstance(result.data, list)
        assert result.data == [
            'atl1',
            'den1',
            'dfw1',
            'jfk1',
            'ord1',
        ]
