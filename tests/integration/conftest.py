from pathlib import Path

import pytest
from agents import RunConfig
from agents.extensions.models.litellm_model import LitellmModel
from agents.mcp import MCPServerStdio, MCPServerStdioParams

from infrahub_mcp.server import infrahub_agent

CURRENT_DIRECTORY = Path(__file__).parent.resolve()
ROOT_DIRECTORY = CURRENT_DIRECTORY.parent.parent.resolve()


@pytest.fixture(scope="session")
def main_prompt() -> str:
    return infrahub_agent()


@pytest.fixture(scope="session")
def run_config() -> RunConfig:
    """RunConfig that routes inference to Claude via litellm."""
    return RunConfig(model=LitellmModel(model="anthropic/claude-sonnet-4-20250514"))


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
