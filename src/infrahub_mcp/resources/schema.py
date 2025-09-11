from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastmcp import Context, FastMCP
from pydantic import Field

from infrahub_mcp.utils import MCPResponse, MCPToolStatus

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient

mcp = FastMCP(name="Infrahub Schema Resources", version="1.0.0")


@mcp.resource(
    uri="infrahub://branch/{branch}/schema",
    description="All available schema kinds and their attributes for a given branch.",
    mime_type="application/json",
    # TODO: Add audience and priorities
    # annotations=Annotations(),
    tags={"schema"},
)
async def schema_all(
    ctx: Context,
    branch: Annotated[
        str | None,
        Field(default=None, description="Branch name to read schema. Defaults to the default branch if not specified."),
    ],
) -> dict:
    """Return the complete schema catalog for a branch.

    Parameters
        branch: Branch name to read schema from.

    Returns
        MCPResponse with success status and objects.
    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client

    try:
        data = await client.schema.all(branch=branch)
        return MCPResponse(
            status=MCPToolStatus.SUCCESS, data=data
        ).model_dump()  # Convert Pydantic models to dicts for JSON serialization

    # FIXME: Be more specific with exception handling once SDK exceptions are defined
    except Exception as exc:  # noqa: BLE001
        return MCPResponse(
            status=MCPToolStatus.ERROR,
            error=f"Failed to fetch schema catalog for branch '{branch}': {type(exc).__name__}",
            remediation="Verify the branch exists and your credentials/SDK connectivity are valid.",
        ).model_dump()  # Convert Pydantic models to dicts for JSON serialization


@mcp.resource(
    uri="infrahub://branch/{branch}/schema/{kind}",
    description="Schema for a specific kind within a given branch.",
    mime_type="application/json",
    # TODO: Add audience and priorities
    # annotations=Annotations(),
    tags={"schema"},
)
async def schema_by_kind(
    ctx: Context,
    branch: str = Field(description="Branch name to read schema from"),
    kind: str = Field(description="Node kind to fetch, e.g. 'Device'"),
) -> dict:
    """Return a single kind's schema for a branch.

    Parameters
    branch: Branch name to read schema from.
    kind: Kind of the schema to retrieve.

    Returns
        MCPResponse with success status and objects.
    """
    if not kind or not kind.strip():
        return MCPResponse(
            status=MCPToolStatus.ERROR,
            error="Parameter 'kind' must be a non-empty string.",
            remediation="Provide a valid kind, e.g. 'Device' or 'Site'.",
        ).model_dump()  # Convert Pydantic models to dicts for JSON serialization

    client: InfrahubClient = ctx.request_context.lifespan_context.client
    try:
        data = await client.schema.get(kind=kind, branch=branch)
        if not data:
            msg = f"Schema kind '{kind}' not found in branch '{branch}'."
            remediation = (
                f"List available kinds via resource 'infrahub://branch/{branch}/schema' and pick an existing kind."
            )
            return MCPResponse(
                status=MCPToolStatus.ERROR,
                error=msg,
                remediation=remediation,
            ).model_dump()  # Convert Pydantic models to dicts for JSON serialization
        return MCPResponse(
            status=MCPToolStatus.SUCCESS, data=data
        ).model_dump()  # Convert Pydantic models to dicts for JSON serialization
    # FIXME: Be more specific with exception handling once SDK exceptions are defined
    except Exception as exc:  # noqa: BLE001
        msg = f"Failed to fetch schema kind '{kind}' in branch '{branch}': {type(exc).__name__}"
        return MCPResponse(
            status=MCPToolStatus.ERROR,
            error=msg,
            remediation="Confirm the branch exists and the kind name is correct; check server/SDK logs for details.",
        ).model_dump()  # Convert Pydantic models to dicts for JSON serialization
