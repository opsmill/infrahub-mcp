from typing import Any

import anthropic
import pytest
from deepeval import assert_test
from deepeval.dataset.golden import Golden
from deepeval.metrics.answer_relevancy.answer_relevancy import AnswerRelevancyMetric
from deepeval.test_case.llm_test_case import LLMTestCase, ToolCall
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import Tool as McpTool

goldens = [
    Golden(
        name="find_kind",
        input="what is the proper kind for a device",
        expected_output="The proper kind for a device is InfraDevice.",
        expected_tools=[ToolCall(name="search_nodes", input_parameters=None)],
    ),
]


def _mcp_tool_to_anthropic(tool: McpTool) -> dict[str, Any]:
    """Convert an MCP tool definition to an Anthropic tool parameter."""
    return {
        "name": tool.name,
        "description": tool.description or "",
        "input_schema": tool.inputSchema,
    }


def _extract_tool_calls(messages: list[anthropic.types.Message]) -> list[ToolCall]:
    """Extract tool calls from a sequence of Anthropic Messages."""
    tools: list[ToolCall] = []
    for msg in messages:
        for block in msg.content:
            if block.type == "tool_use":
                tool_call = ToolCall(
                    name=block.name,
                    input_parameters=block.input if block.input else None,  # type: ignore[attr-defined]
                )
                tools.append(tool_call)
    return tools


def _extract_text(message: anthropic.types.Message) -> str:
    """Extract text content from an Anthropic Message."""
    return next((b.text for b in message.content if b.type == "text"), "")


async def _run_agent_loop(
    client: anthropic.AsyncAnthropic,
    system: str,
    tools: list[dict[str, Any]],
    user_input: str,
    session: ClientSession,
    max_turns: int = 10,
) -> tuple[list[anthropic.types.Message], str]:
    """Run a tool-use agentic loop using the Anthropic API and MCP session."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_input}]
    all_responses: list[anthropic.types.Message] = []

    for _ in range(max_turns):
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=system,
            tools=tools,
            messages=messages,
        )
        all_responses.append(response)

        if response.stop_reason != "tool_use":
            break

        # Append assistant response
        messages.append({"role": "assistant", "content": response.content})

        # Execute each tool call via MCP
        tool_results: list[dict[str, Any]] = []
        for block in response.content:
            if block.type == "tool_use":
                mcp_result = await session.call_tool(block.name, arguments=block.input)  # type: ignore[attr-defined]
                result_text = "\n".join(c.text for c in mcp_result.content if hasattr(c, "text"))
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                        "is_error": mcp_result.isError or False,
                    }
                )

        messages.append({"role": "user", "content": tool_results})

    final_text = _extract_text(all_responses[-1]) if all_responses else ""
    return all_responses, final_text


@pytest.mark.parametrize("golden", goldens)
async def test_llm_app(
    anthropic_client: anthropic.AsyncAnthropic,
    main_prompt: str,
    mcp_server_params: dict,
    golden: Golden,
) -> None:
    params = StdioServerParameters(
        command=mcp_server_params["command"],
        args=mcp_server_params["args"],
        env=mcp_server_params["env"],
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            mcp_tools = await session.list_tools()
            anthropic_tools = [_mcp_tool_to_anthropic(t) for t in mcp_tools.tools]

            all_responses, actual_output = await _run_agent_loop(
                client=anthropic_client,
                system=main_prompt,
                tools=anthropic_tools,
                user_input=golden.input,
                session=session,
            )

            tools_called = _extract_tool_calls(all_responses)

            test_case = LLMTestCase(
                name=golden.name,
                input=golden.input,
                actual_output=actual_output,
                tools_called=tools_called,
                expected_tools=golden.expected_tools,
            )

            assert_test(
                test_case=test_case,
                metrics=[
                    AnswerRelevancyMetric(),
                ],
            )
