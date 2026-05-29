"""Write tools for the Infrahub MCP server."""

import logging
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from infrahub_sdk.exceptions import GraphQLError, NodeNotFoundError, SchemaNotFoundError
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.auth import assert_writable_branch
from infrahub_mcp.schema import get_valid_kinds_summary
from infrahub_mcp.utils import (
    SESSION_BRANCH_STATE_KEY,
    _log_and_raise_error,
    get_client,
    get_default_branch,
    get_or_create_session_branch,
)

# pylint: disable=duplicate-code
mcp: FastMCP = FastMCP(name="Infrahub Write")
logger = logging.getLogger(__name__)

_NO_IDENTIFIER_MSG = "Provide either 'id' (UUID) or 'hfid' (human-friendly ID list) to identify the node."
_BRANCH_NOTE = "All writes target the active session branch, auto-created on the first write of a session."


@mcp.tool(
    tags={"nodes", "write"},
    annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=False),
)
async def node_upsert(  # pylint: disable=too-many-locals
    ctx: Context,
    kind: Annotated[
        str,
        Field(description="Kind of the node to create or update. Check infrahub://schema."),
    ],
    data: Annotated[
        dict[str, Any],
        Field(
            description=(
                "Flat {attribute: value} map. See infrahub://schema/{kind} for valid names. "
                "Scalar attributes only; use mutate_graphql for relationships."
            )
        ),
    ],
    id: Annotated[  # noqa: A002  # pylint: disable=redefined-builtin
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
) -> dict[str, Any]:
    """Create or update a node in Infrahub on the active session branch.

    The session branch is auto-created on the first write of the session
    (``mcp/session-YYYYMMDD-<hex>``). Use ``propose_changes`` to open a
    review once your changes are ready.
    To discover available kinds and attributes, read the ``infrahub://schema``
    resource. If your client does not support MCP resources, call the
    ``get_schema`` tool instead.

    - **Create**: omit both ``id`` and ``hfid``.
    - **Update**: supply either ``id`` or ``hfid`` to identify the target node.

    Only scalar attribute fields are accepted in ``data``. To set relationship
    fields, use ``mutate_graphql`` with an appropriate GraphQL mutation.

    Parameters:
        kind: Node kind to create or update.
        data: Flat attribute map ``{attribute_name: value}``.
        id: UUID of the node to update (update mode).
        hfid: Human-friendly ID segments of the node to update (update mode).

    Returns:
        Dict with node id, display_label, and branch on success.
    """
    client = get_client(ctx)
    session_branch = await get_or_create_session_branch(ctx)

    # Validate kind exists
    try:
        schema = await client.schema.get(kind=kind, branch=session_branch)
    except SchemaNotFoundError:
        valid = await get_valid_kinds_summary(client, branch=session_branch)
        await _log_and_raise_error(
            ctx=ctx,
            error=f"Schema not found for kind: {kind}.",
            remediation=f"{valid}\nCall get_schema() for details on any kind.",
        )

    sdk_data = {key: {"value": value} for key, value in data.items()}
    unknown_attrs: list[str] = []

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
                else:
                    unknown_attrs.append(attr_name)
            if unknown_attrs:
                identifier = id or hfid
                logger.warning(
                    "Unknown attribute(s) %s on %s node %s; skipping",
                    unknown_attrs,
                    kind,
                    identifier,
                )
            await node.save()
        else:
            # Create path
            await ctx.info(f"Creating {kind} node on branch {session_branch}")
            node = await client.create(kind=schema.kind, branch=session_branch, **sdk_data)
            await node.save()

    except NodeNotFoundError as exc:
        await _log_and_raise_error(ctx=ctx, error=exc, remediation=_NO_IDENTIFIER_MSG)
    except GraphQLError as exc:
        await _log_and_raise_error(
            ctx=ctx,
            error=exc,
            remediation=f"Check attribute names against infrahub://schema/{kind}.",
        )

    result: dict[str, Any] = {
        "id": node.id,
        "display_label": node.display_label,
        "branch": session_branch,
    }
    if unknown_attrs:
        result["skipped_attributes"] = unknown_attrs
        result["warning"] = (
            f"Attributes {unknown_attrs} are not defined on {kind}. "
            f"Check infrahub://schema/{kind} for valid attribute names."
        )
    return result


@mcp.tool(
    tags={"nodes", "write"},
    annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=True),
)
async def node_delete(
    ctx: Context,
    kind: Annotated[str, Field(description="Kind of the node to delete. Check infrahub://schema.")],
    id: Annotated[  # noqa: A002  # pylint: disable=redefined-builtin
        str | None,
        Field(default=None, description="UUID of the node to delete."),
    ] = None,
    hfid: Annotated[
        list[str] | None,
        Field(default=None, description="Human-friendly ID of the node to delete, as a list of string segments."),
    ] = None,
) -> dict[str, Any]:
    """Delete a node in Infrahub on the active session branch.

    The deletion is applied to the session branch only and is not visible on the
    default branch until a proposed change is merged.
    To discover available kinds, read the ``infrahub://schema`` resource.
    If your client does not support MCP resources, call the ``get_schema``
    tool instead.

    Parameters:
        kind: Kind of the node.
        id: UUID of the node to delete.
        hfid: Human-friendly ID segments of the node to delete.

    Returns:
        Dict confirming deletion on success.
    """
    if id is None and hfid is None:
        await _log_and_raise_error(
            ctx=ctx,
            error="No node identifier provided.",
            remediation=_NO_IDENTIFIER_MSG,
        )

    client = get_client(ctx)
    session_branch = await get_or_create_session_branch(ctx)

    try:
        schema = await client.schema.get(kind=kind, branch=session_branch)
    except SchemaNotFoundError:
        valid = await get_valid_kinds_summary(client, branch=session_branch)
        await _log_and_raise_error(
            ctx=ctx,
            error=f"Schema not found for kind: {kind}.",
            remediation=f"{valid}\nCall get_schema() for details on any kind.",
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
        await _log_and_raise_error(ctx=ctx, error=exc, remediation="Verify the id/hfid is correct.")
    except GraphQLError as exc:
        await _log_and_raise_error(ctx=ctx, error=exc)

    return {"deleted_id": id or hfid, "branch": session_branch}


@mcp.tool(
    tags={"branches", "write"},
    annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=False),
)
async def propose_changes(
    ctx: Context,
    title: Annotated[
        str,
        Field(description="Title for the proposed change (equivalent to a PR title)."),
    ],
    description: Annotated[
        str | None,
        Field(default=None, description="Optional description explaining the motivation for the changes."),
    ] = None,
    destination_branch: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Branch to merge into. Defaults to the instance's "
                "default branch (resolved automatically). "
                "Override only when merging into a non-default branch."
            ),
        ),
    ] = None,
) -> dict[str, Any]:
    """Open a proposed change (pull request) from the active session branch to the default branch.

    Creates a ``CoreProposedChange`` in Infrahub so a human can review, approve,
    and merge the changes made during this session. The session branch remains
    active after calling this — you can continue making changes.

    Parameters:
        title: Title of the proposed change.
        description: Optional description of the changes.
        destination_branch: Target branch (default: resolved from Infrahub's default branch).

    Returns:
        Dict with proposed change id and branch details on success.
    """
    client = get_client(ctx)
    session_branch = await ctx.get_state(SESSION_BRANCH_STATE_KEY)
    if session_branch is None:
        await _log_and_raise_error(
            ctx=ctx,
            error="No session branch exists yet.",
            remediation="Make at least one write (node_upsert / node_delete) before proposing changes.",
        )

    if destination_branch is None:
        branches = await client.branch.all()
        resolved = next((name for name, b in branches.items() if b.is_default), "main")
        destination_branch = resolved

    await ctx.info(f"Creating proposed change from branch {session_branch} to {destination_branch}")

    try:
        node = await client.create(
            kind="CoreProposedChange",
            name={"value": title},
            source_branch={"value": session_branch},
            destination_branch={"value": destination_branch},
            description={"value": description or ""},
        )
        await node.save()
    except GraphQLError as exc:
        await _log_and_raise_error(ctx=ctx, error=exc)

    return {
        "id": node.id,
        "title": title,
        "source_branch": session_branch,
        "destination_branch": destination_branch,
    }


@mcp.tool(
    tags={"graphql", "write"},
    annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=True),
)
async def mutate_graphql(
    ctx: Context,
    query: Annotated[str, Field(description="GraphQL mutation to execute.")],
    branch: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Branch to execute the mutation against. "
                "Defaults to the auto-created session branch (recommended). "
                "Override only when targeting a specific non-default branch."
            ),
        ),
    ] = None,
) -> dict[str, Any]:
    """Execute a GraphQL mutation against Infrahub — use only for complex writes that typed tools can't express.

    Prefer ``node_upsert`` (create/update scalar attributes) or ``node_delete``
    (remove a node) for straightforward changes; they validate against the
    schema and produce clearer audit entries. Reach for ``mutate_graphql``
    when you need relationship edits, bulk operations, or any mutation shape
    not covered by the typed tools. For reads, use ``query_graphql``.

    The mutation targets the session branch by default, which is auto-created
    on the first write of the session (``mcp/session-YYYYMMDD-<hex>``).

    To discover available kinds and their attributes, read the ``infrahub://schema``
    resource or call the ``get_schema`` tool.
    For the full GraphQL SDL, read ``infrahub://graphql-schema``.

    Parameters:
        query: GraphQL mutation to execute.
        branch: Branch to execute against. Defaults to the session branch.

    Returns:
        The result of the mutation.
    """
    client = get_client(ctx)

    if branch is None:
        branch = await get_or_create_session_branch(ctx)
    else:
        try:
            default_branch = await get_default_branch(ctx)
            assert_writable_branch(branch, default_branch=default_branch)
        except ValueError as exc:
            await _log_and_raise_error(ctx=ctx, error=str(exc))

    try:
        data = await client.execute_graphql(query=query, branch_name=branch)
    except GraphQLError as exc:
        await _log_and_raise_error(
            ctx,
            exc,
            remediation=(
                "Call get_schema() to list valid kinds, or "
                "get_schema(kind='...') to see attributes and filters. "
                "Read infrahub://graphql-schema for the full GraphQL SDL."
            ),
        )

    return data
