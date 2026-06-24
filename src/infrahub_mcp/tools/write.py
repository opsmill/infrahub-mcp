"""Write tools for the Infrahub MCP server."""

import logging
from collections.abc import Iterator
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from graphql import OperationType
from graphql import parse as gql_parse
from graphql.error import GraphQLSyntaxError
from infrahub_sdk.exceptions import GraphQLError, NodeNotFoundError, SchemaNotFoundError
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.schema import get_valid_kinds_summary
from infrahub_mcp.utils import (
    _log_and_raise_error,
    get_client,
    get_or_create_session_branch,
    get_session_branch,
    recover_if_session_branch_stale,
    reset_or_switch_session_branch,
)

# pylint: disable=duplicate-code
mcp: FastMCP = FastMCP(name="Infrahub Write")
logger = logging.getLogger(__name__)

_NO_IDENTIFIER_MSG = "Provide either 'id' (UUID) or 'hfid' (human-friendly ID list) to identify the node."
_BRANCH_NOTE = "All writes target the active session branch, auto-created on the first write of a session."

_READ_ONLY_MARKERS = ("read-only", "read only", "has been merged")


def _is_read_only_error(exc: GraphQLError) -> bool:
    """Return True if a GraphQL error indicates the target branch is merged/read-only."""
    text = str(exc).lower()
    return any(marker in text for marker in _READ_ONLY_MARKERS)


async def _maybe_recover_read_only(ctx: Context, exc: GraphQLError) -> None:
    """Recover from a session branch merged/deleted mid-write (FR-011).

    Only acts when the error *looks* branch-related (cheap pre-filter) **and**
    Infrahub confirms the session branch is no longer writable: it then clears the
    cached branch and raises a retryable error so the next write provisions a fresh
    one. The failed mutation is deliberately not replayed (an arbitrary mutation
    could partially apply). For any other error — including an unrelated read-only
    *attribute* error on a perfectly writable branch — it returns so the caller's
    normal error handling proceeds and the valid session branch is preserved.
    """
    if not _is_read_only_error(exc):
        return
    detail = await recover_if_session_branch_stale(ctx)
    if detail is None:
        return
    await _log_and_raise_error(
        ctx=ctx,
        error=f"Session branch {detail}; it was cleared during the write.",
        remediation="Retry the operation — a fresh session branch will be created automatically.",
    )


# Infrahub built-in mutations that operate independently of the target branch and
# would escape session-branch isolation: branch management can merge into / delete the
# default branch outside the propose_changes review gate; schema mutations alter the
# instance globally. Names confirmed against infrahub-sdk; update if the SDK adds more.
_BLOCKED_MUTATIONS = frozenset(
    {
        "BranchCreate",
        "BranchDelete",
        "BranchMerge",
        "BranchRebase",
        "BranchUpdate",
        "BranchValidate",
        "SchemaDropdownAdd",
        "SchemaDropdownRemove",
        "SchemaEnumAdd",
        "SchemaEnumRemove",
    }
)


def _collect_field_names(node: Any) -> Iterator[str]:
    """Yield every field name reachable from a node's selection set.

    Recurses through inline fragments and nested selections so a privileged field
    cannot hide inside ``... on Mutation { ... }``. Named fragment definitions are
    scanned separately as top-level document definitions.
    """
    selection_set = getattr(node, "selection_set", None)
    if selection_set is None:
        return
    for selection in selection_set.selections:
        if getattr(selection, "kind", "") == "field":
            yield selection.name.value
        yield from _collect_field_names(selection)


def _assert_no_privileged_mutations(query: str) -> None:
    """Reject non-mutation operations and branch-/schema-management mutations in ``mutate_graphql``.

    Branch/schema mutations bypass session-branch isolation and the human-review
    gate, so they are not valid session-scoped writes — branch changes go through
    ``reset_session_branch`` and merges through ``propose_changes``. Field names are
    inspected recursively (inline fragments, fragment definitions) so a blocked
    mutation cannot be smuggled in via ``... on Mutation { ... }``.
    """
    try:
        document = gql_parse(query)
    except GraphQLSyntaxError as exc:
        msg = f"Invalid GraphQL syntax: {exc}. Fix the mutation and retry; read infrahub://graphql-schema for the SDL."
        raise ToolError(msg) from exc
    for definition in document.definitions:
        operation = getattr(definition, "operation", None)
        if operation is not None and operation != OperationType.MUTATION:
            msg = "mutate_graphql only accepts GraphQL mutations; use query_graphql for reads."
            raise ToolError(msg)
        for name in _collect_field_names(definition):
            if name in _BLOCKED_MUTATIONS:
                msg = (
                    f"Mutation '{name}' is not allowed via mutate_graphql. Branch and schema "
                    "management bypass session-branch isolation and the review gate. Use "
                    "reset_session_branch for branch changes and propose_changes to merge."
                )
                raise ToolError(msg)


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
        await _maybe_recover_read_only(ctx, exc)
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
        await _maybe_recover_read_only(ctx, exc)
        await _log_and_raise_error(
            ctx=ctx,
            error=exc,
            remediation=(
                f"Verify the node exists and has no relationships blocking deletion; check infrahub://schema/{kind}."
            ),
        )

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
    session_branch = get_session_branch(ctx)
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
        await _log_and_raise_error(
            ctx=ctx,
            error=exc,
            remediation="Verify the destination branch exists and your session branch has changes to propose.",
        )

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
    query: Annotated[str, Field(description="GraphQL mutation to execute on the active session branch.")],
) -> dict[str, Any]:
    """Execute a GraphQL mutation against Infrahub — use only for complex writes that typed tools can't express.

    Prefer ``node_upsert`` (create/update scalar attributes) or ``node_delete``
    (remove a node) for straightforward changes; they validate against the
    schema and produce clearer audit entries. Reach for ``mutate_graphql``
    when you need relationship edits, bulk operations, or any mutation shape
    not covered by the typed tools. For reads, use ``query_graphql``.

    The mutation always runs on the **active session branch** (auto-created on the
    first write of the session, ``mcp/session-YYYYMMDD-<hex>``). There is no branch
    override — writes are isolated to the session, and changes reach the default
    branch only through ``propose_changes`` and human review. To target a different
    branch deliberately, switch the session with ``reset_session_branch`` first.
    Branch- and schema-management mutations are rejected.

    To discover available kinds and their attributes, read the ``infrahub://schema``
    resource or call the ``get_schema`` tool.
    For the full GraphQL SDL, read ``infrahub://graphql-schema``.

    Parameters:
        query: GraphQL mutation to execute on the session branch.

    Returns:
        The result of the mutation.
    """
    _assert_no_privileged_mutations(query)
    client = get_client(ctx)
    branch = await get_or_create_session_branch(ctx)

    try:
        data = await client.execute_graphql(query=query, branch_name=branch)
    except GraphQLError as exc:
        await _maybe_recover_read_only(ctx, exc)
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


@mcp.tool(
    tags={"session", "write"},
    annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=False, destructiveHint=False),
)
async def reset_session_branch(
    ctx: Context,
    branch: Annotated[
        str | None,
        Field(
            default=None,
            description=(
                "Target branch. Omit to drop the cached session branch so the next write "
                "creates a fresh one. Provide a name to switch this session to that branch "
                "(created if it does not exist and the name matches the configured pattern)."
            ),
        ),
    ] = None,
) -> dict[str, Any]:
    """Reset or switch the active session branch for the current MCP session.

    Use this to recover or take control of which branch your writes target:

    - **No ``branch``** — clears the cached session branch; the next write
      auto-creates a fresh one. Useful after you have merged your work and want
      to start a new change set.
    - **With ``branch``** — points this session at the named branch. If it does
      not exist and the name matches the configured branch pattern, it is created
      and reported. The instance default branch and merged/read-only branches are
      rejected.

    Note: a merged or deleted session branch is recovered **automatically** on the
    next write — this tool is the explicit override on top of that.

    Affects only the calling session; other sessions are unaffected.

    Parameters:
        branch: Target branch name, or omit to reset to a fresh auto-created branch.

    Returns:
        Dict with ``session_branch`` (active branch after the call, or null),
        ``previous_branch``, ``created`` (bool), and ``action``
        (``reset`` | ``switched`` | ``created``).
    """
    return await reset_or_switch_session_branch(ctx, branch)
