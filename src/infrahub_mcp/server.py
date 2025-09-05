from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from fastmcp import FastMCP
from infrahub_sdk.client import InfrahubClient

from infrahub_mcp.tools.branch import mcp as branch_mcp
from infrahub_mcp.tools.gql import mcp as graphql_mcp
from infrahub_mcp.tools.nodes import mcp as nodes_mcp
from infrahub_mcp.tools.schema import mcp as schema_mcp


@dataclass
class AppContext:
    client: InfrahubClient


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:  # noqa: ARG001, RUF029
    """Manages application lifecycle with type-safe context for the FastMCP server."""
    client = InfrahubClient()
    try:
        yield AppContext(client=client)
    finally:
        pass


mcp: FastMCP = FastMCP(name="Infrahub MCP Server", version="0.1.0", lifespan=app_lifespan)

# Mount the various MCPs to the main server
mcp.mount(branch_mcp)
mcp.mount(graphql_mcp)
mcp.mount(nodes_mcp)
mcp.mount(schema_mcp)
