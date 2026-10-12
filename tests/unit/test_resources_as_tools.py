"""INFRAHUB_MCP_RESOURCES_AS_TOOLS adds list_resources and read_resource (spec FR-012, FR-014, FR-015, SC-005).

``server.py`` reads its configuration once at import, so each case starts the
server in a fresh interpreter. Infrahub is replaced by a fake branch list.
"""

from __future__ import annotations

import json
import os
import subprocess  # noqa: S404 - runs the server in a child process to test startup config
import sys
from typing import Any

import pytest

_RUN_SERVER = """
import asyncio, json, logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from fastmcp import Client
import infrahub_mcp.resources.branches as branches
from infrahub_mcp.server import mcp

audit = []
class Capture(logging.Handler):
    def emit(self, record):
        audit.append(record.getMessage())
logging.getLogger("infrahub_mcp.middleware").addHandler(Capture())
logging.getLogger("infrahub_mcp.middleware").setLevel(logging.INFO)

client = MagicMock()
client.branch.all = AsyncMock(return_value={"main": SimpleNamespace(is_default=True, description="")})

async def main():
    out = {}
    with patch.object(branches, "get_client", return_value=client):
        async with Client(mcp) as c:
            out["tools"] = sorted(t.name for t in await c.list_tools())
            out["instructions"] = c.instructions
            if "read_resource" in out["tools"]:
                try:
                    result = await c.call_tool(
                        "read_resource", {"uri": "infrahub://branches"}, raise_on_error=False
                    )
                except Exception as exc:  # protocol-level rejection, e.g. by the passthrough gate
                    out["is_error"] = True
                    out["error"] = str(exc)
                else:
                    out["is_error"] = result.is_error
                    out["text"] = result.content[0].text if result.content else ""
    out["audit"] = audit
    print(json.dumps(out))

asyncio.run(main())
"""


def _run(**settings: str) -> dict[str, Any]:
    env = {
        **os.environ,
        "INFRAHUB_ADDRESS": "http://infrahub.invalid",
        "INFRAHUB_API_TOKEN": "unused",
        "INFRAHUB_MCP_ENV_FILE": "",
        "INFRAHUB_MCP_LOG_LEVEL": "info",
        **settings,
    }
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", _RUN_SERVER], env=env, capture_output=True, text=True, check=True, timeout=60
    )
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_setting_off_adds_no_tool() -> None:
    out = _run(INFRAHUB_MCP_RESOURCES_AS_TOOLS="false")
    assert "list_resources" not in out["tools"]
    assert "read_resource" not in out["tools"]
    assert "read_resource" not in out["instructions"]


@pytest.mark.parametrize("read_only", ["false", "true"])
def test_setting_on_reads_the_branch_list_in_one_call(read_only: str) -> None:
    """SC-005, and FR-014: the tools are listed and callable in read-only mode too."""
    out = _run(INFRAHUB_MCP_RESOURCES_AS_TOOLS="true", INFRAHUB_MCP_READ_ONLY=read_only)
    assert {"list_resources", "read_resource"} <= set(out["tools"])
    assert out["is_error"] is False
    assert json.loads(out["text"]) == {"main": {"is_default": True, "description": ""}}
    assert 'read_resource(uri="infrahub://branches")' in out["instructions"]


def test_setting_on_audits_the_resource_read() -> None:
    out = _run(INFRAHUB_MCP_RESOURCES_AS_TOOLS="true")
    assert any(line.startswith("tool_call tool=read_resource") for line in out["audit"])
    assert any(line.startswith("resource_read uri=infrahub://branches") for line in out["audit"])


def test_setting_on_keeps_token_passthrough_closed() -> None:
    """Without a credential, read_resource is rejected like a direct resource read."""
    out = _run(INFRAHUB_MCP_RESOURCES_AS_TOOLS="true", INFRAHUB_MCP_AUTH_MODE="token-passthrough")
    assert "read_resource" in out["tools"]
    assert out["is_error"] is True
    assert "Authentication required" in out["error"]
