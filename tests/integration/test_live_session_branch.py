"""Live integration tests against a running Infrahub.

Reproduces the customer scenario end-to-end through the MCP tools (via FastMCP's
in-memory ``Client`` — exercising the real tool wiring) and uses the raw SDK for
setup/teardown the tools intentionally cannot do (merge/delete branches).

Skipped unless ``INFRAHUB_ADDRESS`` is set, so normal unit CI is unaffected:

    INFRAHUB_ADDRESS=http://localhost:8000 \
    INFRAHUB_API_TOKEN=06438eb2-8019-4776-878c-0941b1f1d1ec \
    uv run pytest tests/integration/test_live_session_branch.py -q
"""

from __future__ import annotations

import contextlib
import os
import uuid
from typing import Any

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from infrahub_sdk import Config, InfrahubClient

from infrahub_mcp.server import mcp

pytestmark = pytest.mark.skipif(
    not os.environ.get("INFRAHUB_ADDRESS"),
    reason="requires a live Infrahub (set INFRAHUB_ADDRESS / INFRAHUB_API_TOKEN)",
)

ADDR = os.environ.get("INFRAHUB_ADDRESS", "")
TOKEN = os.environ.get("INFRAHUB_API_TOKEN", "")


def _raw() -> InfrahubClient:
    return InfrahubClient(config=Config(address=ADDR, api_token=TOKEN))


def _data(result: Any) -> dict[str, Any]:
    """Extract the tool's returned dict from a FastMCP CallToolResult."""
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return data
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    import json  # noqa: PLC0415

    return json.loads(result.content[0].text)


def _tag() -> str:
    return f"mcp-live-{uuid.uuid4().hex[:8]}"


async def _delete_branch(raw: InfrahubClient, name: str) -> None:
    with contextlib.suppress(Exception):
        await raw.branch.delete(branch_name=name)


async def _delete_tag(raw: InfrahubClient, name: str, branch: str = "main") -> None:
    with contextlib.suppress(Exception):
        node = await raw.get(kind="BuiltinTag", name__value=name, branch=branch)
        await node.delete()


async def test_live_recovers_after_session_branch_merged() -> None:
    """THE customer bug: merge the session branch, then the next write recovers onto a fresh branch."""
    raw = _raw()
    branches: list[str] = []
    tag1, tag2 = _tag(), _tag()
    try:
        async with Client(mcp) as cl:
            r1 = _data(await cl.call_tool("node_upsert", {"kind": "BuiltinTag", "data": {"name": tag1}}))
            b1 = r1["branch"]
            branches.append(b1)
            assert b1.startswith("mcp/session-")

            # The intended end-of-work step that used to wedge the session.
            await raw.branch.merge(branch_name=b1)

            # Next write must succeed on a NEW branch — no "merged and is read-only" error, no restart.
            r2 = _data(await cl.call_tool("node_upsert", {"kind": "BuiltinTag", "data": {"name": tag2}}))
            b2 = r2["branch"]
            branches.append(b2)
            assert b2 != b1, "expected auto-recovery onto a fresh session branch"
            assert b2.startswith("mcp/session-")
    finally:
        for b in branches:
            await _delete_branch(raw, b)
        await _delete_tag(raw, tag1)  # tag1 was merged onto main


async def test_live_recovers_after_session_branch_deleted() -> None:
    """Regression: a deleted session branch also recovers."""
    raw = _raw()
    branches: list[str] = []
    try:
        async with Client(mcp) as cl:
            b1 = _data(await cl.call_tool("node_upsert", {"kind": "BuiltinTag", "data": {"name": _tag()}}))["branch"]
            branches.append(b1)
            await raw.branch.delete(branch_name=b1)
            b2 = _data(await cl.call_tool("node_upsert", {"kind": "BuiltinTag", "data": {"name": _tag()}}))["branch"]
            branches.append(b2)
            assert b2 != b1
    finally:
        for b in branches:
            await _delete_branch(raw, b)


async def test_live_reset_switch_create_and_reject_default() -> None:
    raw = _raw()
    branches: list[str] = []
    conformant = f"mcp/session-20990101-{uuid.uuid4().hex[:8]}"
    try:
        async with Client(mcp) as cl:
            b1 = _data(await cl.call_tool("node_upsert", {"kind": "BuiltinTag", "data": {"name": _tag()}}))["branch"]
            branches.append(b1)

            reset = _data(await cl.call_tool("reset_session_branch", {}))
            assert reset["action"] == "reset"
            assert reset["previous_branch"] == b1
            assert reset["session_branch"] is None

            created = _data(await cl.call_tool("reset_session_branch", {"branch": conformant}))
            branches.append(conformant)
            assert created["action"] == "created"
            assert created["session_branch"] == conformant

            with pytest.raises(ToolError):
                await cl.call_tool("reset_session_branch", {"branch": "main"})
    finally:
        for b in branches:
            await _delete_branch(raw, b)


async def test_live_blocks_privileged_mutations_via_mutate_graphql() -> None:
    raw = _raw()
    branches: list[str] = []
    tag = _tag()
    try:
        async with Client(mcp) as cl:
            with pytest.raises(ToolError):
                await cl.call_tool("mutate_graphql", {"query": 'mutation { BranchMerge(data: {name: "main"}) { ok } }'})
            # inline-fragment smuggling is also blocked
            with pytest.raises(ToolError):
                await cl.call_tool(
                    "mutate_graphql",
                    {"query": 'mutation { ... on Mutation { BranchMerge(data: {name: "main"}) { ok } } }'},
                )
            # a normal data mutation still works (and opens a session branch)
            res = _data(
                await cl.call_tool(
                    "mutate_graphql",
                    {"query": f'mutation {{ BuiltinTagCreate(data: {{name: {{value: "{tag}"}}}}) {{ ok }} }}'},
                )
            )
            assert res.get("BuiltinTagCreate", {}).get("ok") is True
            info = _data(await cl.call_tool("get_session_info", {}))
            branches.append(info["session_branch"])
            assert info["has_session_branch"] is True
    finally:
        for b in branches:
            await _delete_branch(raw, b)
