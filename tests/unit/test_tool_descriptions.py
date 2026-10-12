"""Tool, parameter and prompt text name a tool the assistant can call (spec FR-004 to FR-007, FR-017, SC-002)."""

from __future__ import annotations

import re
from typing import Any

import pytest
from fastmcp import Client

from infrahub_mcp.server import mcp

# Arguments needed to render each prompt; optional arguments are added so every branch of the text is checked.
_PROMPT_ARGUMENTS: dict[str, list[dict[str, str]]] = {
    "infrahub_agent": [{}],
    "answer_infra_question": [{"question": "How many sites?"}, {"question": "List sites", "kind_hint": "LocationSite"}],
    "make_infra_change": [{"description": "add a VLAN"}, {"description": "add a VLAN", "kind": "IpamVLAN"}],
    "explore_schema": [{}, {"kind": "LocationSite"}],
}

_FILTERS_ON_THE_QUERY = "directly on the kind's query"


@pytest.fixture(autouse=True)
def _infrahub_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The server lifespan validates the Infrahub settings; no request reaches Infrahub in these tests."""
    monkeypatch.setenv("INFRAHUB_ADDRESS", "http://infrahub.invalid")
    monkeypatch.setenv("INFRAHUB_API_TOKEN", "unused")


async def _tools() -> dict[str, Any]:
    async with Client(mcp) as client:
        return {tool.name: tool for tool in await client.list_tools()}


def _parameter_description(tool: Any, parameter: str) -> str:
    return tool.input_schema["properties"][parameter].get("description", "")


async def _texts() -> list[tuple[str, str]]:
    """Every tool description, parameter description and rendered prompt, labelled for error messages."""
    texts: list[tuple[str, str]] = []
    async with Client(mcp) as client:
        for tool in await client.list_tools():
            texts.append((f"tool {tool.name}", tool.description or ""))
            for name, schema in tool.input_schema.get("properties", {}).items():
                texts.append((f"tool {tool.name} parameter {name}", schema.get("description", "")))
        for prompt in await client.list_prompts():
            for arguments in _PROMPT_ARGUMENTS[prompt.name]:
                result = await client.get_prompt(prompt.name, arguments=arguments)
                body = "\n".join(message.content.text for message in result.messages)  # type: ignore[attr-defined]
                texts.append((f"prompt {prompt.name} {arguments}", body))
    return texts


async def test_every_prompt_is_rendered() -> None:
    async with Client(mcp) as client:
        assert {prompt.name for prompt in await client.list_prompts()} == set(_PROMPT_ARGUMENTS)


async def test_resource_uris_come_with_a_tool() -> None:
    """SC-002: text that names an infrahub:// URI also names a tool for that step."""
    offenders = [
        label
        for label, text in await _texts()
        if "infrahub://" in text and "get_schema" not in text and "read_resource" not in text
    ]
    assert not offenders


async def test_no_text_depends_on_resource_support() -> None:
    """FR-004: the schema step does not depend on whether the client reads resources."""
    offenders = [label for label, text in await _texts() if "does not support MCP resources" in text]
    assert not offenders


@pytest.mark.parametrize("tool_name", ["get_nodes", "search_nodes", "query_graphql", "node_upsert"])
async def test_descriptions_name_get_schema(tool_name: str) -> None:
    tools = await _tools()
    assert "get_schema" in (tools[tool_name].description or "")


@pytest.mark.parametrize(
    ("tool_name", "parameter"),
    [("get_nodes", "kind"), ("get_nodes", "filters"), ("search_nodes", "kind"), ("node_upsert", "kind")],
)
async def test_parameters_name_get_schema(tool_name: str, parameter: str) -> None:
    tools = await _tools()
    assert "get_schema" in _parameter_description(tools[tool_name], parameter)


async def test_get_schema_does_not_prefer_the_resource() -> None:
    """FR-006."""
    tools = await _tools()
    description = tools["get_schema"].description or ""
    assert "Prefer reading" not in description
    assert "first" in description


async def test_query_graphql_states_the_filter_syntax() -> None:
    """FR-007: one example with a filter key directly on the kind's query."""
    tools = await _tools()
    description = tools["query_graphql"].description or ""
    assert 'no "filters" argument' in description
    assert re.search(r"[A-Z]\w+\(\w+__value: ", description)


@pytest.mark.parametrize(("tool_name", "parameter"), [("get_schema", None), ("get_nodes", "filters")])
async def test_filter_keys_are_linked_to_graphql(tool_name: str, parameter: str | None) -> None:
    """FR-017: the same keys are GraphQL arguments placed directly on the kind's query."""
    tools = await _tools()
    tool = tools[tool_name]
    text = (tool.description or "") if parameter is None else _parameter_description(tool, parameter)
    assert "query_graphql" in text
    assert _FILTERS_ON_THE_QUERY in text
