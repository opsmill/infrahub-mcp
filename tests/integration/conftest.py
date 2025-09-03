from pathlib import Path

import pytest
from agents.mcp import MCPServerStdio, MCPServerStdioParams

from infrahub_mcp.utils import get_prompt

CURRENT_DIRECTORY = Path(__file__).parent.resolve()
ROOT_DIRECTORY = CURRENT_DIRECTORY.parent.parent.resolve()


@pytest.fixture(scope="session")
def main_prompt() -> str:
    return get_prompt("main")


@pytest.fixture(scope="session")
def local_mcp_server() -> MCPServerStdio:
    """Fixture to provide a local MCP server for testing."""

    return MCPServerStdio(
        name="infrahub",
        params=MCPServerStdioParams(
            command="uv",
            cwd=str(ROOT_DIRECTORY.absolute()),
            args=[
                "--directory",
                str(ROOT_DIRECTORY.absolute()),
                "run",
                "fastmcp",
                "run",
                "--no-banner",
                "src/infrahub_mcp/server.py:mcp",
            ],
            env={
                "INFRAHUB_ADDRESS": "https://sandbox.infrahub.app",
                "INFRAHUB_USERNAME": "otto",
                "INFRAHUB_PASSWORD": "infrahub",
            },
        ),
        cache_tools_list=True,
    )
