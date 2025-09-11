from typing import TYPE_CHECKING, Annotated

from fastmcp import Context, FastMCP
from infrahub_sdk.branch import BranchData
from infrahub_sdk.exceptions import GraphQLError
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.utils import MCPResponse, MCPToolStatus, _log_and_return_error

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClient

mcp: FastMCP = FastMCP(name="Infrahub Branches")


@mcp.tool(
    tags={"branches", "create"},
    annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True, destructiveHint=False),
)
async def branch_create(
    ctx: Context,
    name: Annotated[str, Field(description="Name of the branch to create.")],
    sync_with_git: Annotated[bool, Field(default=False, description="Whether to sync the branch with git.")],
) -> MCPResponse:
    """Create a new branch in infrahub.

    Parameters:
        name: Name of the branch to create.
        sync_with_git: Whether to sync the branch with git. Defaults to False.

    Returns:
        Dictionary with success status and branch details.
    """

    client: InfrahubClient = ctx.request_context.lifespan_context.client
    await ctx.info(f"Creating branch {name} in Infrahub...")

    try:
        branch = await client.branch.create(branch_name=name, sync_with_git=sync_with_git, background_execution=False)

    except GraphQLError as exc:
        return await _log_and_return_error(ctx=ctx, error=exc, remediation="Check the branch name or your permissions.")

    return MCPResponse(
        status=MCPToolStatus.SUCCESS,
        data={
            "name": branch.name,
            "id": branch.id,
        },
    )


@mcp.tool(tags={"branches", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def get_branches(ctx: Context) -> MCPResponse:
    """Retrieve all branches from infrahub."""

    client: InfrahubClient = ctx.request_context.lifespan_context.client
    await ctx.info("Fetching all branches from Infrahub...")

    branches: dict[str, BranchData] = await client.branch.all()

    return MCPResponse(status=MCPToolStatus.SUCCESS, data=branches)
