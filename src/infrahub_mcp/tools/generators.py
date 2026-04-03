"""Generator workflow tools for the Infrahub MCP server."""

import logging
from typing import TYPE_CHECKING, Annotated, Any

import toon
from fastmcp import Context, FastMCP
from infrahub_sdk.exceptions import GraphQLError, NodeNotFoundError
from infrahub_sdk.task.exceptions import TaskNotFoundError
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.utils import _log_and_raise_error, get_or_create_session_branch

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient

mcp: FastMCP = FastMCP(name="Infrahub Generators")
logger = logging.getLogger(__name__)

_RUN_GENERATOR_MUTATION = """
mutation CoreGeneratorDefinitionRun($id: String!, $nodes: [String!]) {
  CoreGeneratorDefinitionRun(
    wait_until_completion: false
    data: { id: $id, nodes: $nodes }
  ) {
    task {
      id
    }
  }
}
"""


@mcp.tool(tags={"generators", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def get_generator_targets(
    ctx: Context,
    generator_id: Annotated[
        str,
        Field(description="UUID of the CoreGeneratorDefinition."),
    ],
    branch: Annotated[
        str | None,
        Field(default=None, description="Branch to query. Defaults to the default branch."),
    ] = None,
) -> str:
    """List the valid target nodes for a generator definition.

    Fetches the generator's target group and returns its members.
    Use this to discover which nodes can be passed to ``run_generator``.

    Parameters:
        generator_id: UUID of the generator definition.
        branch: Branch to query.

    Returns:
        TOON-encoded list of target nodes with id, display_label, and kind.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client  # type: ignore[union-attr]
    req_id = ctx.request_id
    await ctx.info(
        f"Fetching generator targets: request_id={req_id!r}, generator_id={generator_id!r}, branch={branch!r}"
    )

    # Fetch the generator definition
    try:
        gen = await client.get(kind="CoreGeneratorDefinition", id=generator_id, branch=branch, include=["targets"], prefetch_relationships=True)
    except NodeNotFoundError:
        await _log_and_raise_error(
            ctx=ctx,
            error=f"Generator definition not found: {generator_id}",
            remediation="Read infrahub://generators to see available generator definitions.",
        )

    # Fetch the group and its members
    try:
        group = await client.get(kind="CoreStandardGroup", id=targets_rel.id, branch=branch, include=["members"], prefetch_relationships=True)
    except NodeNotFoundError:
        await _log_and_raise_error(
            ctx=ctx,
            error=f"Target group {targets_rel.id} not found.",
            remediation="The generator's target group may have been deleted.",
        )

    results: list[dict[str, str]] = [
        {
            "id": peer.id,
            "display_label": peer.display_label or peer.id,
            "kind": peer.typename,
        }
        for peer in group.members.peers
    ]

    await ctx.debug(f"Found {len(results)} targets for generator {generator_id} (request_id={req_id!r})")
    if not results:
        return "Target group has no members."
    return toon.encode(results)


@mcp.tool(
    tags={"generators", "write"},
    annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=False),
)
async def run_generator(
    ctx: Context,
    generator_id: Annotated[
        str,
        Field(
            description=(
                "UUID of the CoreGeneratorDefinition to run. "
                "Read infrahub://generators to discover available generators."
            )
        ),
    ],
    target_node_ids: Annotated[
        list[str] | None,
        Field(
            default=None,
            description=(
                "Specific target node IDs to run the generator on. "
                "Omit to run on all targets in the generator's target group. "
                "Use get_generator_targets() to discover valid target nodes."
            ),
        ),
    ] = None,
) -> dict[str, Any]:
    """Run a generator definition on the session branch.

    Executes the ``CoreGeneratorDefinitionRun`` mutation asynchronously and
    returns a task ID. Use ``get_task_status`` to poll for completion.

    The generator runs on the session branch (auto-created on the first write
    of the session). This keeps changes isolated until a proposed change is
    merged.

    Parameters:
        generator_id: UUID of the generator definition.
        target_node_ids: Optional list of specific target node IDs.

    Returns:
        Dict with task_id, generator_id, and branch.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client  # type: ignore[union-attr]
    session_branch = await get_or_create_session_branch(ctx)

    await ctx.info(
        f"Running generator {generator_id} on branch {session_branch} "
        f"with {len(target_node_ids) if target_node_ids else 'all'} targets"
    )

    variables: dict[str, Any] = {"id": generator_id}
    if target_node_ids:
        variables["nodes"] = target_node_ids

    try:
        data = await client.execute_graphql(
            query=_RUN_GENERATOR_MUTATION,
            variables=variables,
            branch_name=session_branch,
        )
    except GraphQLError as exc:
        await _log_and_raise_error(
            ctx=ctx,
            error=exc,
            remediation=(
                "Verify the generator_id with infrahub://generators and target node IDs with get_generator_targets()."
            ),
        )

    task_id = data.get("CoreGeneratorDefinitionRun", {}).get("task", {}).get("id")
    if not task_id:
        await _log_and_raise_error(
            ctx=ctx,
            error="Generator started but no task ID was returned.",
            remediation="The generator may have run synchronously. Check Infrahub task logs.",
        )

    await ctx.info(f"Generator started: task_id={task_id}")
    return {"task_id": task_id, "generator_id": generator_id, "branch": session_branch}


@mcp.tool(tags={"tasks", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def get_task_status(
    ctx: Context,
    task_id: Annotated[
        str,
        Field(description="UUID of the task to check (as returned by run_generator)."),
    ],
    include_logs: Annotated[
        bool,
        Field(default=False, description="Include task log entries in the response."),
    ] = False,
) -> dict[str, Any]:
    """Check the status of an Infrahub task.

    Use after ``run_generator`` to poll for completion. The task progresses
    through states like ``pending``, ``running``, and ``completed``.

    Parameters:
        task_id: UUID of the task.
        include_logs: Whether to include log entries.

    Returns:
        Dict with task id, title, state, conclusion, progress, and timestamps.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client  # type: ignore[union-attr]
    req_id = ctx.request_id
    await ctx.info(f"Checking task status: request_id={req_id!r}, task_id={task_id!r}")

    try:
        task = await client.task.get(
            id=task_id,
            include_logs=include_logs,
            include_related_nodes=True,
        )
    except TaskNotFoundError:
        await _log_and_raise_error(
            ctx=ctx,
            error=f"Task not found: {task_id}",
            remediation="The task may not have been created yet. Wait a moment and retry.",
        )

    result: dict[str, Any] = {
        "id": task.id,
        "title": task.title,
        "state": task.state.value,
        "progress": task.progress,
        "created_at": task.created_at.isoformat(),
        "updated_at": task.updated_at.isoformat(),
        "related_nodes": [{"id": rn.id, "kind": rn.kind} for rn in task.related_nodes],
    }

    if include_logs:
        result["logs"] = [
            {
                "message": log.message,
                "severity": log.severity,
                "timestamp": log.timestamp.isoformat(),
            }
            for log in task.logs
        ]

    await ctx.debug(f"Task {task_id} state={task.state.value} (request_id={req_id!r})")
    return result
