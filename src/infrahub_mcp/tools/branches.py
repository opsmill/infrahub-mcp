"""Branch management tools for the Infrahub MCP server."""

import logging
from typing import TYPE_CHECKING, Annotated, Any

from fastmcp import Context, FastMCP
from infrahub_sdk.exceptions import BranchNotFoundError, GraphQLError
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.utils import _log_and_raise_error, set_session_branch_name

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient

mcp: FastMCP = FastMCP(name="Infrahub Branches")
logger = logging.getLogger(__name__)


@mcp.tool(
    tags={"branches", "write"},
    annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=False),
)
async def create_branch(
    ctx: Context,
    name: Annotated[
        str,
        Field(description="Name for the new branch."),
    ],
    description: Annotated[
        str | None,
        Field(default=None, description="Optional description for the branch."),
    ] = None,
    sync_with_git: Annotated[
        bool,
        Field(default=False, description="Whether to sync the branch with a Git repository."),
    ] = False,
    set_as_session_branch: Annotated[
        bool,
        Field(
            default=True,
            description=(
                "Set the new branch as the active session branch. "
                "When True, subsequent writes and generators will target this branch."
            ),
        ),
    ] = True,
) -> dict[str, Any]:
    """Create a new branch in Infrahub and optionally set it as the session branch.

    Use this instead of raw GraphQL mutations for branch creation. When
    ``set_as_session_branch`` is True (the default), all subsequent write
    operations (``node_upsert``, ``node_delete``, ``run_generator``) will
    target the new branch.

    Read ``infrahub://branches`` to see existing branches before creating.

    Parameters:
        name: Branch name.
        description: Optional branch description.
        sync_with_git: Whether to sync with Git (default False).
        set_as_session_branch: Set as active session branch (default True).

    Returns:
        Dict with branch name, id, sync_with_git, and whether it was set as the session branch.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client  # type: ignore[union-attr]

    await ctx.info(f"Creating branch: {name}")

    try:
        branch_data = await client.branch.create(
            branch_name=name,
            description=description or "",
            sync_with_git=sync_with_git,
            wait_until_completion=True,
        )
    except GraphQLError as exc:
        await _log_and_raise_error(
            ctx=ctx,
            error=exc,
            remediation="Check the branch name is valid and not already taken. Read infrahub://branches to see existing branches.",
        )

    if set_as_session_branch:
        previous = await set_session_branch_name(ctx, name)
        if previous:
            await ctx.info(f"Session branch changed from {previous} to {name}")
        else:
            await ctx.info(f"Session branch set to {name}")

    return {
        "name": branch_data.name,
        "id": branch_data.id,
        "sync_with_git": branch_data.sync_with_git,
        "is_session_branch": set_as_session_branch,
    }


@mcp.tool(
    tags={"branches", "write"},
    annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True, destructiveHint=False),
)
async def set_session_branch(
    ctx: Context,
    branch_name: Annotated[
        str,
        Field(
            description=(
                "Name of an existing branch to use as the session branch. "
                "Read infrahub://branches to discover available branches."
            ),
        ),
    ],
) -> dict[str, Any]:
    """Point the active session at an existing Infrahub branch.

    After calling this, all write operations (``node_upsert``, ``node_delete``,
    ``run_generator``) will target the specified branch instead of auto-creating
    a new session branch.

    The branch must already exist. Read ``infrahub://branches`` to see available
    branches, or use ``create_branch`` to create a new one.

    Parameters:
        branch_name: Name of the existing branch to target.

    Returns:
        Dict with the new and previous session branch names.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client  # type: ignore[union-attr]

    try:
        await client.branch.get(branch_name=branch_name)
    except BranchNotFoundError:
        await _log_and_raise_error(
            ctx=ctx,
            error=f"Branch not found: {branch_name}",
            remediation="Read infrahub://branches to see available branches, or use create_branch to create a new one.",
        )

    previous = await set_session_branch_name(ctx, branch_name)
    if previous and previous != branch_name:
        await ctx.info(f"Session branch changed from {previous} to {branch_name}")
    else:
        await ctx.info(f"Session branch set to {branch_name}")

    return {
        "session_branch": branch_name,
        "previous_session_branch": previous,
    }
