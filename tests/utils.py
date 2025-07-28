import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from agents import Agent
from agents.result import RunResult
from deepeval.test_case.llm_test_case import ToolCall
from openai.types.responses import (
    ResponseFunctionToolCall,
)

CURRENT_DIRECTORY = Path(__file__).parent.resolve()
ROOT_DIRECTORY = CURRENT_DIRECTORY.parent.resolve()


@asynccontextmanager
async def agent_context(**kwargs: Any) -> AsyncIterator[Agent]:
    """Context manager to create an Agent with MCP server.

    The Context manager will connect the MCP server(s) and cleanup after the agent is done.
    """
    agent = Agent(**kwargs)
    # Connect all MCP servers
    for mcp_server in agent.mcp_servers:
        await mcp_server.connect()
    try:
        yield agent
    finally:
        # Cleanup all MCP servers
        for mcp_server in agent.mcp_servers:
            await mcp_server.cleanup()


def extract_tools(result: RunResult) -> list[ToolCall]:
    """Extract tool calls during an Agent run from the result."""
    tools: list[ToolCall] = []
    for response in result.raw_responses:
        for item in response.output:
            if isinstance(item, ResponseFunctionToolCall) and item.status == "completed":
                tool_call = ToolCall(
                    name=item.name, input_parameters=json.loads(item.arguments) if item.arguments else None
                )
                tools.append(tool_call)
    return tools
