from typing import TYPE_CHECKING, Annotated, Any

from fastmcp import Context, FastMCP
from infrahub_sdk.exceptions import BranchNotFoundError, SchemaNotFoundError
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.constants import NAMESPACES_INTERNAL
from infrahub_mcp.utils import MCPResponse, MCPToolStatus, _log_and_return_error

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClient

mcp: FastMCP = FastMCP(name="Infrahub Schemas")


@mcp.tool(tags={"schemas", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def get_schema_mapping(
    ctx: Context,
    branch: Annotated[
        str | None,
        Field(default=None, description="Branch to retrieve the mapping from. Defaults to None (uses default branch)."),
    ],
) -> MCPResponse:
    """List all schema nodes and generics available in Infrahub

    Parameters:
        branch: Branch to retrieve the mapping from. Defaults to None (uses default branch).

    Returns:
        Dictionary with success status and schema mapping.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client
    if branch:
        await ctx.info(f"Fetching schema mapping for {branch} from Infrahub...")
    else:
        await ctx.info("Fetching schema mapping from Infrahub...")

    try:
        all_schemas = await client.schema.all(branch=branch)
    except BranchNotFoundError as exc:
        return await _log_and_return_error(ctx=ctx, error=exc, remediation="Check the branch name or your permissions.")

    # TODO: Should we add the description ?
    schema_mapping = {
        kind: node.label or "" for kind, node in all_schemas.items() if node.namespace not in NAMESPACES_INTERNAL
    }

    return MCPResponse(
        status=MCPToolStatus.SUCCESS,
        data=schema_mapping,
    )


@mcp.tool(tags={"schemas", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def get_schema(
    ctx: Context,
    kind: Annotated[str, Field(description="Schema Kind to retrieve.")],
    branch: Annotated[
        str | None,
        Field(default=None, description="Branch to retrieve the schema from. Defaults to None (uses default branch)."),
    ],
) -> MCPResponse:
    """Retrieve the full schema for a specific kind.
    This includes attributes, relationships, and their types.

    Parameters:
        kind: Schema Kind to retrieve.
        branch: Branch to retrieve the schema from. Defaults to None (uses default branch).

    Returns:
        Dictionary with success status and schema.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client
    await ctx.info(f"Fetching schema of {kind} from Infrahub...")

    try:
        schema = await client.schema.get(kind=kind, branch=branch)
    except SchemaNotFoundError:
        error_msg = f"Schema not found for kind: {kind}."
        remediation_msg = "Use the `get_schema_mapping` tool to list available kinds."
        return await _log_and_return_error(ctx=ctx, error=error_msg, remediation=remediation_msg)
    except BranchNotFoundError as exc:
        return await _log_and_return_error(ctx=ctx, error=exc, remediation="Check the branch name or your permissions.")

    schema = await client.schema.get(kind=kind, branch=branch)

    return MCPResponse(
        status=MCPToolStatus.SUCCESS,
        data=schema.model_dump(),
    )


@mcp.tool(tags={"schemas", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def get_schemas(
    ctx: Context,
    branch: Annotated[
        str | None,
        Field(default=None, description="Branch to retrieve schemas from. Defaults to None (uses default branch)."),
    ],
    exclude_profiles: Annotated[
        bool, Field(default=True, description="Whether to exclude Profile schemas. Defaults to True.")
    ],
    exclude_templates: Annotated[
        bool, Field(default=True, description="Whether to exclude Template schemas. Defaults to True.")
    ],
) -> MCPResponse:
    """Retrieve all schemas from Infrahub, optionally excluding Profiles and Templates.

    Parameters:
        infrahub_client: Infrahub client to use
        branch: Branch to retrieve schemas from
        exclude_profiles: Whether to exclude Profile schemas. Defaults to True.
        exclude_templates: Whether to exclude Template schemas. Defaults to True.

    Returns:
        Dictionary with success status and schemas.

    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client
    await ctx.info(f"Fetching all schemas in branch {branch or 'main'} from Infrahub...")

    try:
        all_schemas = await client.schema.all(branch=branch)
    except BranchNotFoundError as exc:
        return await _log_and_return_error(ctx=ctx, error=exc, remediation="Check the branch name or your permissions.")

    # Filter out Profile and Template if requested
    filtered_schemas = {}
    for kind, schema in all_schemas.items():
        if (exclude_templates and schema.namespace == "Template") or (
            exclude_profiles and schema.namespace == "Profile"
        ):
            continue
        filtered_schemas[kind] = schema.model_dump()

    return MCPResponse(
        status=MCPToolStatus.SUCCESS,
        data=filtered_schemas,
    )
