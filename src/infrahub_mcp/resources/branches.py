import json
from typing import TYPE_CHECKING, Any

from fastmcp import Context, FastMCP

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient

mcp: FastMCP = FastMCP(name="Infrahub Branch Resources")


@mcp.resource(
    "infrahub://branches",
    name="Branches",
    description=(
        "All branches currently present in this Infrahub instance, "
        "including the active session branch when one has been created. "
        "Read this to know which branches are available before querying or proposing changes."
    ),
    mime_type="application/json",
)
async def branches(ctx: Context) -> str:
    """Return all branches as a JSON object keyed by branch name.

    Parameters:
        ctx: MCP request context providing access to the Infrahub client.

    Returns:
        Compact JSON object keyed by branch name, where each value contains
        ``is_default`` (bool) and ``description`` (str) fields.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client  # type: ignore[union-attr]

    raw = await client.branch.all()

    result: dict[str, Any] = {
        name: {"is_default": b.is_default, "description": b.description or ""} for name, b in raw.items()
    }
    return json.dumps(result, separators=(",", ":"))
