from typing import TYPE_CHECKING

from fastmcp import Context, FastMCP

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClient

mcp: FastMCP = FastMCP(name="Infrahub Branch")


@mcp.tool
async def branch_create(ctx: Context, name: str, sync_with_git: bool = False) -> dict:
    """Create a new branch in infrahub."""

    client: InfrahubClient = ctx.request_context.lifespan_context.client
    branch = await client.branch.create(branch_name=name, sync_with_git=sync_with_git, background_execution=False)

    return {"name": branch.name, "id": branch.id}
