import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastmcp import FastMCP
from infrahub_sdk.client import InfrahubClient

from infrahub_mcp.prompts.prompts import mcp as prompts_mcp
from infrahub_mcp.resources.branches import mcp as branches_resources_mcp
from infrahub_mcp.resources.schema import mcp as schema_resources_mcp
from infrahub_mcp.tools.gql import mcp as graphql_mcp
from infrahub_mcp.tools.nodes import mcp as nodes_mcp
from infrahub_mcp.tools.write import mcp as write_mcp
from infrahub_mcp.utils import AppContext, get_prompt

logger = logging.getLogger(__name__)


def _validate_env() -> None:
    """Validate required environment variables at startup and raise with clear guidance."""
    address = os.environ.get("INFRAHUB_ADDRESS")
    if not address:
        msg = "INFRAHUB_ADDRESS is required. Set it to the URL of your Infrahub instance (e.g. http://localhost:8000)."
        raise RuntimeError(msg)

    api_token = os.environ.get("INFRAHUB_API_TOKEN")
    username = os.environ.get("INFRAHUB_USERNAME")
    password = os.environ.get("INFRAHUB_PASSWORD")

    if not api_token and not (username and password):
        msg = "Authentication required. Set INFRAHUB_API_TOKEN  —or—  both INFRAHUB_USERNAME and INFRAHUB_PASSWORD."
        raise RuntimeError(msg)


@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:  # noqa: ARG001, RUF029
    """Manage the application lifecycle: validate config, create client, yield context."""
    _validate_env()
    client = InfrahubClient()
    try:
        yield AppContext(client=client)
    finally:
        pass  # InfrahubClient manages its own connection lifecycle


mcp: FastMCP = FastMCP(name="Infrahub MCP Server", version="0.1.2", lifespan=app_lifespan)


@mcp.prompt()
def infrahub_agent() -> str:
    """System prompt for the Infrahub infrastructure agent."""
    return get_prompt("main")


# Resources — consumed as context, not as tool calls
mcp.mount(schema_resources_mcp)
mcp.mount(branches_resources_mcp)

# Prompts — parameterized workflow guides
mcp.mount(prompts_mcp)

# Tools
mcp.mount(graphql_mcp)
mcp.mount(nodes_mcp)
mcp.mount(write_mcp)
