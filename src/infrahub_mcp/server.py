from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastmcp import FastMCP
from infrahub_sdk.client import InfrahubClient

from infrahub_mcp.prompts.usage_guide import mcp as prompt_usage_guide_mcp
from infrahub_mcp.resources.schema import mcp as resource_schema_mcp
from infrahub_mcp.tools.branch import mcp as tool_branch_mcp
from infrahub_mcp.tools.gql import mcp as tool_graphql_mcp
from infrahub_mcp.tools.nodes import mcp as tool_nodes_mcp
from infrahub_mcp.tools.schema import mcp as tool_schema_mcp

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


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

# Resources
mcp.mount(resource_schema_mcp)

# Prompts
mcp.mount(prompt_usage_guide_mcp)

# Tools
mcp.mount(tool_branch_mcp)
mcp.mount(tool_graphql_mcp)
mcp.mount(tool_nodes_mcp)
mcp.mount(tool_schema_mcp)
