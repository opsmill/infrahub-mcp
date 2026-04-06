"""Session introspection tools for the Infrahub MCP server."""

import os
from typing import Any

from fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

mcp: FastMCP = FastMCP(name="Infrahub Session")


@mcp.tool(tags={"session", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def get_session_info(ctx: Context) -> dict[str, Any]:
    """Return the current MCP session state.

    Reports the active session branch (if any) and the Infrahub instance address.
    Useful for multi-agent environments to understand connection state.

    Returns:
        Dict with ``session_branch`` (str or null), ``infrahub_address``, and ``has_session_branch``.
    """
    app_ctx = ctx.request_context.lifespan_context  # type: ignore[union-attr]
    await ctx.debug("Returning session info")
    return {
        "session_branch": app_ctx.session_branch,
        "has_session_branch": app_ctx.session_branch is not None,
        "infrahub_address": os.environ.get("INFRAHUB_ADDRESS", "unknown"),
    }
