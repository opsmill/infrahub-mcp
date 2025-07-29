from typing import Any
from fastmcp import Context, FastMCP
from infrahub_sdk import InfrahubClient
from infrahub_sdk.exceptions import BranchNotFoundError, SchemaNotFoundError
from infrahub_sdk.schema.main import GenericSchemaAPI, NodeSchemaAPI

from infrahub_mcp_server.constants import NAMESPACES_INTERNAL
from infrahub_mcp_server.utils import _log_and_return_error

mcp: FastMCP = FastMCP(name="Infrahub Schema")


@mcp.tool(tags=["schemas"])
async def get_schema_mapping(
    ctx: Context,
    branch: str | None = None,
) -> dict[str, Any]:
    """List all schema nodes and generics available in Infrahub

    Parameters:
        branch: Branch to retrieve the mapping from. Defaults to None (uses default branch).

    Returns:
        Dictionary of mapping and metadata.

    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client
    ctx.info("Fetching schema mapping from Infrahub...")

    try:
        all_schemas = await client.schema.all(branch=branch)
    except BranchNotFoundError as exc:  # noqa: BLE001
        return _log_and_return_error(
            ctx=ctx,
            error=exc,
            remediation="Check the branch name or your permissions."
        )

    # TODO: Should we add the description ?
    schema_mapping = {
        kind: node.label or ""
        for kind, node in all_schemas.items()
        if node.namespace not in NAMESPACES_INTERNAL
    }
    return {
        "success": True,
        "data": schema_mapping
    }


@mcp.tool(tags=["schemas"])
async def get_schema(
    ctx: Context,
    kind: str,
    branch: str | None = None,
) -> dict[str, Any]:
    """Retrieve the full schema for a specific kind.
    This includes attributes, relationships, and their types.

    Parameters:
        kind: Schema Kind to retrieve.
        branch: Branch to retrieve the schema from. Defaults to None (uses default branch).

    Returns:
        Dictionary of schema and metadata.

    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client
    ctx.info(f"Fetching schema of {kind} from Infrahub...")

    try:
        schema = await client.schema.get(kind=kind, branch=branch)
    except SchemaNotFoundError:
        error_msg = f"Schema not found for kind: {kind}."
        remediation_msg = "Use the `get_schema_mapping` tool to list available kinds."
        return _log_and_return_error(
            ctx=ctx,
            error=error_msg,
            remediation=remediation_msg
        )
    except BranchNotFoundError as exc:  # noqa: BLE001
        return _log_and_return_error(
            ctx=ctx,
            error=exc,
            remediation="Check the branch name or your permissions."
        )

    schema = await client.schema.get(kind=kind, branch=branch)
    return schema.model_dump()

@mcp.tool(tags=["schemas"])
async def get_schemas(
    ctx: Context,
    branch: str | None = None,
    exclude_profiles: bool = True,
    exclude_templates: bool = True,
) -> dict[str, Any]:
    """Retrieve all schemas from Infrahub, optionally excluding Profiles and Templates.

    Parameters:
        infrahub_client: Infrahub client to use
        branch: Branch to retrieve schemas from
        exclude_profiles: Whether to exclude Profile schemas. Defaults to True.
        exclude_templates: Whether to exclude Template schemas. Defaults to True.

    Returns:
        Dictionary of schemas with kind as key and schema object as value

    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client
    ctx.info(f"Fetching all schemas in branch {branch or 'main'} from Infrahub...")

    try:
        all_schemas = await client.schema.all(branch=branch)
    except BranchNotFoundError as exc:  # noqa: BLE001
        return _log_and_return_error(
            ctx=ctx,
            error=exc,
            remediation="Check the branch name or your permissions."
        )

    # Filter out Profile and Template if requested
    filtered_schemas = {}
    for kind, schema in all_schemas.items():
        if (exclude_templates and schema.namespace == "Template") or (
            exclude_profiles and schema.namespace == "Profile"
        ):
            continue
        filtered_schemas[kind] = schema.model_dump()

    # schemas = [
    #         {
    #             "kind": schema.kind,
    #             "namespace": schema.namespace,
    #             "name": schema.name,
    #             "description": schema.description,
    #             "label": schema.label,
    #             "icon": schema.icon,
    #             "type": "Generic" if isinstance(schema, GenericSchemaAPI) else "Node",
    #             "human_friendly_id": schema.human_friendly_id,
    #             "uniqueness_constraints": schema.uniqueness_constraints,
    #             "branch_support": getattr(schema, "branch", None),
    #             "attributes": [
    #                 {
    #                     "name": attr.name,
    #                     "kind": attr.kind,
    #                     "description": attr.description,
    #                     "optional": attr.optional,
    #                     "unique": attr.unique,
    #                 }
    #                 for attr in schema.attributes
    #             ],
    #             "relationships": [
    #                 {
    #                     "name": rel.name,
    #                     "peer": rel.peer,
    #                     "kind": rel.kind,
    #                     "cardinality": rel.cardinality,
    #                     "description": rel.description,
    #                     "hierarchical": rel.hierarchical,
    #                 }
    #                 for rel in schema.relationships
    #             ],
    #             "used_by": getattr(schema, "used_by", []) if isinstance(schema, GenericSchemaAPI) else [],
    #             "inherit_from": getattr(schema, "inherit_from", []) if hasattr(schema, "inherit_from") else [],
    #         }
    #         for schema in filtered_schemas.values()
    #     ],

    return {
        "success": True,
        "data": filtered_schemas,
    }