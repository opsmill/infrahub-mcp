"""Session introspection tools for the Infrahub MCP server."""

import os
from typing import Any

from fastmcp import Context, FastMCP
from mcp.types import ToolAnnotations

from infrahub_mcp.utils import get_session_branch

mcp: FastMCP = FastMCP(name="Infrahub Session")


@mcp.tool(tags={"session", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def get_session_info(ctx: Context) -> dict[str, Any]:
    """Return the current MCP session state — call before writes to know which branch they target.

    Reports the active session branch (if any) and the Infrahub instance address.
    A session branch is lazily auto-created on the first write tool call
    (``node_upsert`` / ``node_delete`` / ``mutate_graphql``) and is named
    ``mcp/session-YYYYMMDD-<hex>``. Before that first write, ``session_branch``
    is ``None`` and all read tools target the default branch.

    Typical uses:

    - Confirm which branch a proposed change would merge from.
    - Decide whether a write is about to open a new session branch.
    - Display the active branch to the user.

    Returns:
        Dict with ``session_branch`` (str or null), ``infrahub_address``, and ``has_session_branch``.
    """
    await ctx.debug("Returning session info")
    session_branch = get_session_branch(ctx)
    return {
        "session_branch": session_branch,
        "has_session_branch": session_branch is not None,
        "infrahub_address": os.environ.get("INFRAHUB_ADDRESS", "unknown"),
    }
