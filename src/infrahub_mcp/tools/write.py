from typing import TYPE_CHECKING, Annotated, Any

from fastmcp import Context, FastMCP
from infrahub_sdk.exceptions import GraphQLError, NodeNotFoundError, SchemaNotFoundError
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.utils import MCPResponse, MCPToolStatus, _log_and_return_error, get_or_create_session_branch

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient

mcp: FastMCP = FastMCP(name="Infrahub Write")

_NO_IDENTIFIER_MSG = "Provide either 'id' (UUID) or 'hfid' (human-friendly ID list) to identify the node."
_BRANCH_NOTE = "All writes target the active session branch, auto-created on the first write of a session."


@mcp.tool(
    tags={"nodes", "write"},
    annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=False),
)
async def node_upsert(
    ctx: Context,
    kind: Annotated[str, Field(description="Kind of the node to create or update. Check infrahub://schema.")],
    data: Annotated[
        dict[str, Any],
        Field(
            description=(
                "Flat {attribute: value} map. See infrahub://schema/{kind} for valid names. "
                "Scalar attributes only; use query_graphql for relationships."
            )
        ),
    ],
    id: Annotated[  # noqa: A002
        str | None,
        Field(default=None, description="UUID of an existing node to update. Omit to create a new node."),
    ] = None,
    hfid: Annotated[
        list[str] | None,
        Field(
            default=None,
            description=(
                "Human-friendly ID of an existing node to update, as a list of string segments. "
                "Omit to create a new node."
            ),
        ),
    ] = None,
) -> MCPResponse:
    """Create or update a node in Infrahub on the active session branch.

    The session branch is auto-created on the first write of the session
    (``mcp/session-YYYYMMDD-<hex>``). Use ``propose_changes`` to open a
    review once your changes are ready.

    - **Create**: omit both ``id`` and ``hfid``.
    - **Update**: supply either ``id`` or ``hfid`` to identify the target node.

    Only scalar attribute fields are accepted in ``data``. To set relationship
    fields, use ``query_graphql`` with an appropriate GraphQL mutation.

    Parameters:
        kind: Node kind to create or update.
        data: Flat attribute map ``{attribute_name: value}``.
        id: UUID of the node to update (update mode).
        hfid: Human-friendly ID segments of the node to update (update mode).

    Returns:
        MCPResponse with node id and display_label on success.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client  # type: ignore[assignment]
    session_branch = await get_or_create_session_branch(ctx)

    # Validate kind exists
    try:
        schema = await client.schema.get(kind=kind, branch=session_branch)
    except SchemaNotFoundError:
        return await _log_and_return_error(
            ctx=ctx,
            error=f"Schema not found for kind: {kind}.",
            remediation="Read infrahub://schema to list available kinds.",
        )

    sdk_data = {key: {"value": value} for key, value in data.items()}

    try:
        if id is not None or hfid is not None:
            # Update path
            get_kwargs: dict[str, Any] = {"kind": schema.kind, "branch": session_branch}
            if id is not None:
                get_kwargs["id"] = id
            else:
                get_kwargs["hfid"] = hfid

            await ctx.info(f"Updating {kind} node on branch {session_branch}")
            node = await client.get(**get_kwargs)
            for attr_name, attr_payload in sdk_data.items():
                attr = getattr(node, attr_name, None)
                if attr is not None and hasattr(attr, "value"):
                    attr.value = attr_payload["value"]
            await node.save()
        else:
            # Create path
            await ctx.info(f"Creating {kind} node on branch {session_branch}")
            node = await client.create(kind=schema.kind, branch=session_branch, **sdk_data)
            await node.save()

    except NodeNotFoundError as exc:
        return await _log_and_return_error(ctx=ctx, error=exc, remediation=_NO_IDENTIFIER_MSG)
    except GraphQLError as exc:
        return await _log_and_return_error(
            ctx=ctx, error=exc, remediation=f"Check attribute names against infrahub://schema/{kind}."
        )

    return MCPResponse(
        status=MCPToolStatus.SUCCESS,
        data={"id": node.id, "display_label": node.display_label, "branch": session_branch},
    )


@mcp.tool(
    tags={"nodes", "write"},
    annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=True),
)
async def node_delete(
    ctx: Context,
    kind: Annotated[str, Field(description="Kind of the node to delete. Check infrahub://schema.")],
    id: Annotated[  # noqa: A002
        str | None,
        Field(default=None, description="UUID of the node to delete."),
    ] = None,
    hfid: Annotated[
        list[str] | None,
        Field(default=None, description="Human-friendly ID of the node to delete, as a list of string segments."),
    ] = None,
) -> MCPResponse:
    """Delete a node in Infrahub on the active session branch.

    The deletion is applied to the session branch only and is not visible on the
    default branch until a proposed change is merged.

    Parameters:
        kind: Kind of the node.
        id: UUID of the node to delete.
        hfid: Human-friendly ID segments of the node to delete.

    Returns:
        MCPResponse confirming deletion on success.
    """
    if id is None and hfid is None:
        return MCPResponse(
            status=MCPToolStatus.ERROR,
            error="No node identifier provided.",
            remediation=_NO_IDENTIFIER_MSG,
        )

    client: InfrahubClient = ctx.request_context.lifespan_context.client  # type: ignore[assignment]
    session_branch = await get_or_create_session_branch(ctx)

    try:
        schema = await client.schema.get(kind=kind, branch=session_branch)
    except SchemaNotFoundError:
        return await _log_and_return_error(
            ctx=ctx,
            error=f"Schema not found for kind: {kind}.",
            remediation="Read infrahub://schema to list available kinds.",
        )

    try:
        get_kwargs: dict[str, Any] = {"kind": schema.kind, "branch": session_branch}
        if id is not None:
            get_kwargs["id"] = id
        else:
            get_kwargs["hfid"] = hfid

        await ctx.info(f"Deleting {kind} node on branch {session_branch}")
        node = await client.get(**get_kwargs)
        await node.delete()

    except NodeNotFoundError as exc:
        return await _log_and_return_error(ctx=ctx, error=exc, remediation="Verify the id/hfid is correct.")
    except GraphQLError as exc:
        return await _log_and_return_error(ctx=ctx, error=exc)

    return MCPResponse(
        status=MCPToolStatus.SUCCESS,
        data={"deleted_id": id or hfid, "branch": session_branch},
    )


@mcp.tool(
    tags={"branches", "write"},
    annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=False),
)
async def propose_changes(
    ctx: Context,
    title: Annotated[str, Field(description="Title for the proposed change (equivalent to a PR title).")],
    description: Annotated[
        str | None,
        Field(default=None, description="Optional description explaining the motivation for the changes."),
    ] = None,
) -> MCPResponse:
    """Open a proposed change (pull request) from the active session branch to main.

    Creates a ``CoreProposedChange`` in Infrahub so a human can review, approve,
    and merge the changes made during this session. The session branch remains
    active after calling this — you can continue making changes.

    Parameters:
        title: Title of the proposed change.
        description: Optional description of the changes.

    Returns:
        MCPResponse with proposed change id and URL on success.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client  # type: ignore[assignment]
    app_ctx = ctx.request_context.lifespan_context

    if app_ctx.session_branch is None:  # type: ignore[union-attr]
        return MCPResponse(
            status=MCPToolStatus.ERROR,
            error="No session branch exists yet.",
            remediation="Make at least one write (node_upsert / node_delete) before proposing changes.",
        )

    session_branch: str = app_ctx.session_branch  # type: ignore[union-attr]
    await ctx.info(f"Creating proposed change from branch {session_branch}")

    try:
        node = await client.create(
            kind="CoreProposedChange",
            name={"value": title},
            source_branch={"value": session_branch},
            destination_branch={"value": "main"},
            description={"value": description or ""},
        )
        await node.save()
    except GraphQLError as exc:
        return await _log_and_return_error(ctx=ctx, error=exc)

    return MCPResponse(
        status=MCPToolStatus.SUCCESS,
        data={
            "id": node.id,
            "title": title,
            "source_branch": session_branch,
            "destination_branch": "main",
        },
    )
