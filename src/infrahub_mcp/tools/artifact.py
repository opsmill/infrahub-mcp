from typing import TYPE_CHECKING, Annotated

from fastmcp import Context, FastMCP
from infrahub_sdk.exceptions import FeatureNotSupportedError, GraphQLError
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.utils import MCPResponse, MCPToolStatus, _log_and_return_error

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClient

mcp: FastMCP = FastMCP(name="Infrahub Artifacts")


@mcp.tool(
    tags={"artifacts", "generate"},
    annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True, destructiveHint=False),
)
async def generate_artifact(
    ctx: Context,
    artifact_definition_id: Annotated[str, Field(description="ID of the CoreArtifactDefinition to generate.")],
    nodes: Annotated[
        list[str] | None,
        Field(default=None, description="Optional list of node IDs to generate artifacts for."),
    ],
) -> MCPResponse:
    """Generate artifacts from an artifact definition in Infrahub.

    Parameters:
        artifact_definition_id: ID of the CoreArtifactDefinition.
        nodes: Optional list of node IDs to scope the generation.

    Returns:
        Dictionary with generation status and details.
    """

    client: InfrahubClient = ctx.request_context.lifespan_context.client
    await ctx.info(f"Generating artifacts for definition {artifact_definition_id}...")

    try:
        artifact_def = await client.get(kind="CoreArtifactDefinition", id=artifact_definition_id)
        await artifact_def.generate(nodes=nodes)  # type: ignore[attr-defined]
    except GraphQLError as exc:
        return await _log_and_return_error(
            ctx=ctx, error=exc, remediation="Check the artifact definition ID or your permissions."
        )
    except FeatureNotSupportedError as exc:
        return await _log_and_return_error(
            ctx=ctx, error=exc, remediation="Ensure the provided ID belongs to a CoreArtifactDefinition node."
        )

    return MCPResponse(
        status=MCPToolStatus.SUCCESS,
        data={"artifact_definition_id": artifact_definition_id, "nodes": nodes},
    )


@mcp.tool(
    tags={"artifacts", "generate"},
    annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True, destructiveHint=False),
)
async def generate_artifact_for_node(
    ctx: Context,
    kind: Annotated[str, Field(description="Kind of the target node (e.g. 'Device').")],
    node_id: Annotated[str, Field(description="ID of the target node.")],
    artifact_name: Annotated[str, Field(description="Name of the artifact to generate.")],
) -> MCPResponse:
    """Generate a specific artifact for a node in Infrahub.

    Parameters:
        kind: Kind of the target node.
        node_id: ID of the target node.
        artifact_name: Name of the artifact to generate.

    Returns:
        Dictionary with generation status and details.
    """

    client: InfrahubClient = ctx.request_context.lifespan_context.client
    await ctx.info(f"Generating artifact '{artifact_name}' for node {node_id}...")

    try:
        node = await client.get(kind=kind, id=node_id)
        await node.artifact_generate(name=artifact_name)  # type: ignore[attr-defined]
    except GraphQLError as exc:
        return await _log_and_return_error(
            ctx=ctx, error=exc, remediation="Check the node kind, ID, and artifact name."
        )
    except FeatureNotSupportedError as exc:
        return await _log_and_return_error(
            ctx=ctx, error=exc, remediation="Ensure the node is a valid artifact definition target."
        )

    return MCPResponse(
        status=MCPToolStatus.SUCCESS,
        data={"node_id": node_id, "artifact_name": artifact_name},
    )
