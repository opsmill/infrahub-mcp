import os
from pathlib import Path

import pytest
import anthropic

from infrahub_mcp.server import infrahub_agent

CURRENT_DIRECTORY = Path(__file__).parent.resolve()
ROOT_DIRECTORY = CURRENT_DIRECTORY.parent.parent.resolve()


@pytest.fixture(scope="session")
def main_prompt() -> str:
    return infrahub_agent()


@pytest.fixture(scope="session")
def anthropic_client() -> anthropic.AsyncAnthropic:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")
    return anthropic.AsyncAnthropic(api_key=api_key)


@pytest.fixture(scope="session")
def mcp_server_params() -> dict[str, str]:
    """Parameters to launch the local MCP server via stdio."""
    return {
        "command": "uv",
        "args": [
            "--directory",
            str(ROOT_DIRECTORY.absolute()),
            "run",
            "fastmcp",
            "run",
            "--no-banner",
            "src/infrahub_mcp/server.py:mcp",
        ],
        "env": {
            "INFRAHUB_ADDRESS": os.environ.get("INFRAHUB_ADDRESS", "https://sandbox.infrahub.app"),
            "INFRAHUB_USERNAME": os.environ.get("INFRAHUB_USERNAME", "<redacted>"),
            "INFRAHUB_PASSWORD": os.environ.get("INFRAHUB_PASSWORD", "<redacted>"),
        },
    }
