"""The server sends build_instructions(...) for its settings (spec FR-001, FR-015).

``server.py`` reads its configuration once at import, so each variant starts the
server in a fresh interpreter instead of reloading it in this one.
"""

from __future__ import annotations

import json
import os
import subprocess  # noqa: S404 - runs the server in a child process to test startup config
import sys

import pytest

from infrahub_mcp.instructions import build_instructions

_READ_INSTRUCTIONS = """
import asyncio, json
from fastmcp import Client
from infrahub_mcp.server import mcp

async def main():
    async with Client(mcp) as client:
        print(json.dumps({"instructions": client.instructions}))

asyncio.run(main())
"""


def _server_instructions(*, read_only: bool, resources_as_tools: bool) -> str:
    env = {
        **os.environ,
        "INFRAHUB_ADDRESS": "http://infrahub.invalid",
        "INFRAHUB_API_TOKEN": "unused",
        "INFRAHUB_MCP_ENV_FILE": "",
        "INFRAHUB_MCP_READ_ONLY": str(read_only).lower(),
        "INFRAHUB_MCP_RESOURCES_AS_TOOLS": str(resources_as_tools).lower(),
    }
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _READ_INSTRUCTIONS], env=env, capture_output=True, text=True, check=True, timeout=60
    )
    return json.loads(result.stdout.strip().splitlines()[-1])["instructions"]


@pytest.mark.parametrize("read_only", [False, True])
@pytest.mark.parametrize("resources_as_tools", [False, True])
def test_server_sends_instructions_for_its_settings(read_only: bool, resources_as_tools: bool) -> None:
    expected = build_instructions(read_only=read_only, resources_as_tools=resources_as_tools)
    assert _server_instructions(read_only=read_only, resources_as_tools=resources_as_tools) == expected
