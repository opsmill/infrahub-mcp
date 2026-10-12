"""Content rules for the server instructions (specs/004-schema-discovery-guidance/contracts/server-instructions.md)."""

from __future__ import annotations

import pytest
from fastmcp import Client

from infrahub_mcp.instructions import build_instructions
from infrahub_mcp.tools.write import mcp as write_mcp

MAX_INSTRUCTIONS_CHARS = 2000

VARIANTS = [
    pytest.param(False, False, id="read-write"),
    pytest.param(False, True, id="read-write-resource-tools"),
    pytest.param(True, False, id="read-only"),
    pytest.param(True, True, id="read-only-resource-tools"),
]


async def _write_tool_names() -> set[str]:
    async with Client(write_mcp) as client:
        return {tool.name for tool in await client.list_tools()}


@pytest.mark.parametrize(("read_only", "resources_as_tools"), VARIANTS)
@pytest.mark.parametrize(
    "required",
    [
        "get_schema()",
        "get_schema(kind=",
        "Never guess",
        "do not fetch it again",
        "get_nodes",
        "total_count",
        "find_paths",
        "find_reachable",
        'there is no "filters" argument',
        "TOON",
    ],
)
def test_every_variant_contains_the_shared_rules(read_only: bool, resources_as_tools: bool, required: str) -> None:
    assert required in build_instructions(read_only=read_only, resources_as_tools=resources_as_tools)


@pytest.mark.parametrize(("read_only", "resources_as_tools"), VARIANTS)
def test_every_variant_fits_the_size_limit(read_only: bool, resources_as_tools: bool) -> None:
    assert len(build_instructions(read_only=read_only, resources_as_tools=resources_as_tools)) < MAX_INSTRUCTIONS_CHARS


@pytest.mark.parametrize("resources_as_tools", [False, True])
def test_read_write_variants_describe_the_session_branch(resources_as_tools: bool) -> None:
    text = build_instructions(read_only=False, resources_as_tools=resources_as_tools)
    assert "Access: read and write" in text
    assert "get_session_info" in text
    assert "propose_changes" in text


@pytest.mark.parametrize("resources_as_tools", [False, True])
async def test_read_only_variants_name_no_write_tool(resources_as_tools: bool) -> None:
    text = build_instructions(read_only=True, resources_as_tools=resources_as_tools)
    write_tools = await _write_tool_names()
    assert write_tools, "write tools should be registered on the write server"
    assert "Access: read-only" in text
    assert not {name for name in write_tools if name in text}
    assert "session branch" not in text


@pytest.mark.parametrize("read_only", [False, True])
def test_resource_tools_variants_name_the_readable_uris(read_only: bool) -> None:
    text = build_instructions(read_only=read_only, resources_as_tools=True)
    assert 'read_resource(uri="infrahub://branches")' in text
    assert 'read_resource(uri="infrahub://graphql-schema")' in text


@pytest.mark.parametrize("read_only", [False, True])
def test_variants_without_resource_tools_do_not_mention_them(read_only: bool) -> None:
    text = build_instructions(read_only=read_only, resources_as_tools=False)
    assert "read_resource" not in text
    assert "list_resources" not in text
