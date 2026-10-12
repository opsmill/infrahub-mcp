# Quickstart: Verify Schema-Discovery Guidance

**Feature**: [spec.md](./spec.md) | **Date**: 2026-10-12

## 1. Automated checks

```bash
uv sync
uv run invoke format lint
uv run pytest tests/unit/test_instructions.py tests/unit/test_tool_descriptions.py \
  tests/unit/test_resources_as_tools.py tests/unit/test_schema_resources_branch.py
uv run pytest
```

## 2. Check what a client receives

```bash
INFRAHUB_ADDRESS=http://localhost:8000 INFRAHUB_API_TOKEN=<token> \
uv run python -c "
import asyncio
from fastmcp import Client
from infrahub_mcp.server import mcp

async def main():
    async with Client(mcp) as c:
        print(c.instructions)
        print([t.name for t in await c.list_tools()])

asyncio.run(main())
"
```

Expected: the read-and-write text from [contracts/server-instructions.md](./contracts/server-instructions.md), and no `list_resources` / `read_resource` in the tool list. Repeat with `INFRAHUB_MCP_READ_ONLY=true` (read-only text, no write tools) and with `INFRAHUB_MCP_RESOURCES_AS_TOOLS=true` (both resource tools listed).

## 3. Check the issue 191 scenario by hand (SC-001)

1. Start Infrahub with a schema that has a kind the assistant cannot know in advance, and a few nodes of it.
2. Start the server with `INFRAHUB_MCP_READ_ONLY=true` over HTTP.
3. Connect Claude through a client that passes only tools, for example the Claude API MCP connector ([documentation](https://platform.claude.com/docs/en/agents-and-tools/mcp-connector)), which needs a URL Claude can reach. Do not select any prompt.
4. Ask: "How many <kind label> are there?"
5. Record the tool calls. A run passes with at most 3 calls, no guessed kind name, no `filters:` argument in GraphQL. Baseline before this feature: 6 calls ([issue 191](https://github.com/opsmill/infrahub-mcp/issues/191)).
6. Run steps 4 and 5 three times, each in a new conversation. The pull request merges only if at least 2 of the 3 runs pass. Record all three runs in the pull request.

## 4. Check branch-aware resources (SC-004)

On a branch where a kind was added, read `infrahub://schema/<Kind>?branch=<branch>` and call `get_schema(kind="<Kind>", branch="<branch>")`. Both return the same text.
