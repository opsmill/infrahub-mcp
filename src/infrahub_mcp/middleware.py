"""Middleware for the Infrahub MCP server."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware

if TYPE_CHECKING:
    import mcp.types as mt
    from fastmcp.server.middleware import CallNext, MiddlewareContext
    from fastmcp.tools.base import ToolResult

    from infrahub_mcp.config import ServerConfig

# Matches GraphQL mutation operations, allowing for leading whitespace and comments.
_MUTATION_PATTERN = re.compile(r"^\s*(?:#[^\n]*\n\s*)*mutation\b", re.IGNORECASE)


class ReadOnlyMiddleware(Middleware):
    """Block write operations when the server is in read-only mode.

    This middleware intercepts ``tools/call`` requests for the ``query_graphql``
    tool and rejects GraphQL mutations.  Write tools (node_upsert, node_delete,
    propose_changes) are already hidden via conditional mounting, but
    ``query_graphql`` can still execute arbitrary mutations — this middleware
    closes that gap.
    """

    def __init__(self, config: ServerConfig) -> None:
        self.config = config

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> Any:
        if self.config.read_only and context.message.name == "query_graphql":
            arguments = context.message.arguments or {}
            query = arguments.get("query", "")
            if isinstance(query, str) and _MUTATION_PATTERN.match(query):
                msg = "Write operations are disabled in read-only mode."
                raise ToolError(msg)

        return await call_next(context)
