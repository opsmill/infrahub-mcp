from fastmcp import Context, FastMCP
from infrahub_sdk import InfrahubClient
from infrahub_sdk.schema.main import GenericSchemaAPI, NodeSchemaAPI

from infrahub_mcp_server.constants import NAMESPACES_INTERNAL

mcp: FastMCP = FastMCP(name="Infrahub Schema")


@mcp.tool
async def schema_get_mapping(ctx: Context) -> dict[str, str]:
    """List all schema nodes available in Infrahub"""
    client: InfrahubClient = ctx.request_context.lifespan_context.client

    schema = await client.schema.all()
    return {kind: node.label or "" for kind, node in schema.items() if node.namespace not in NAMESPACES_INTERNAL}


@mcp.tool
async def schema_get(ctx: Context, kind: str) -> dict[str, str]:
    """Return the full schema for a specific kind."""
    client: InfrahubClient = ctx.request_context.lifespan_context.client

    schema = await client.schema.get(kind=kind)
    return schema.model_dump()


async def _get_all_schemas(
    *,
    client: InfrahubClient,
    branch: str | None = None,
    exclude_profiles: bool = True,
    exclude_templates: bool = True,
) -> dict[str, GenericSchemaAPI | NodeSchemaAPI]:
    """Get all schemas from Infrahub, optionally excluding Profiles.

    Args:
        infrahub_client: Infrahub client to use
        branch: Branch to retrieve schemas from
        exclude_profiles: Whether to exclude Profile schemas
        exclude_templates: Whether to exclude template schemas

    Returns:
        Dictionary of schemas with kind as key and schema object as value

    """
    all_schemas = await client.schema.all(branch=branch)

    # Filter out Profile and Template if requested
    filtered_schemas = {}
    for kind, schema in all_schemas.items():
        if (exclude_templates and schema.namespace == "Template") or (
            exclude_profiles and schema.namespace == "Profile"
        ):
            continue
        filtered_schemas[kind] = schema

    return filtered_schemas
