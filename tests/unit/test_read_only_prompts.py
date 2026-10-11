"""Read-only mode must not offer write prompts (#192).

``server.py`` reads ``INFRAHUB_MCP_READ_ONLY`` once at import time, so each case
imports the server in a fresh interpreter instead of reloading it in this one.
"""

from __future__ import annotations

import json
import os
import subprocess  # noqa: S404 - runs the server in a child process to test startup config
import sys

import pytest

_LIST_PROMPTS = """
import asyncio, json
from fastmcp import Client
from infrahub_mcp.server import mcp

async def main():
    async with Client(mcp) as client:
        prompts = sorted(p.name for p in await client.list_prompts())
        try:
            await client.get_prompt("make_infra_change", arguments={"description": "add a VLAN"})
            fetchable = True
        except Exception:
            fetchable = False
    print(json.dumps({"prompts": prompts, "fetchable": fetchable}))

asyncio.run(main())
"""


def _server_prompts(read_only: bool) -> dict[str, object]:
    env = {
        **os.environ,
        "INFRAHUB_ADDRESS": "http://infrahub.invalid",
        "INFRAHUB_API_TOKEN": "unused",
        "INFRAHUB_MCP_READ_ONLY": "true" if read_only else "false",
    }
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _LIST_PROMPTS], env=env, capture_output=True, text=True, check=True, timeout=60
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize("read_only", [True, False])
def test_make_infra_change_offered_only_with_write_tools(read_only: bool) -> None:
    result = _server_prompts(read_only)
    assert ("make_infra_change" in result["prompts"]) is not read_only  # type: ignore[operator]
    assert result["fetchable"] is not read_only
    assert {"answer_infra_question", "explore_schema", "infrahub_agent"} <= set(result["prompts"])  # type: ignore[arg-type]
