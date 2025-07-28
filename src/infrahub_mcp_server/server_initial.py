import logging
from typing import TYPE_CHECKING

from fastmcp import Context, FastMCP

from infrahub_sdk.exceptions import GraphQLError, SchemaNotFoundError
from infrahub_sdk.schema.main import GenericSchemaAPI
from infrahub_sdk.types import Order

from .schema import _get_all_schemas
from .utils import convert_node_to_dict

if TYPE_CHECKING:
    from infrahub_sdk import InfrahubClient

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("infrahub_mcp")


# Initialize the FastMCP application
mcp = FastMCP("Infrahub")


def _log_and_return_exception(exc: Exception) -> dict:
    logger.exception(str(exc))
    return {"success": False, "error": str(exc)}


def _log_and_return_error(error: str) -> dict:
    logger.error(str(error))
    return {"success": False, "error": str(error)}


@mcp.tool
async def infrahub_get_nodes(
    ctx: Context,
    kind: str,
    branch: str | None = None,
    filters: dict | None = None,
    partial_match: bool = False,
) -> dict:
    """Retrieve objects from Infrahub.

    Args:
        kind: Kind of the objects to retrieve.
        branch: Branch to retrieve the objects from. Defaults to None (uses default branch).
        filters: Dictionary of filters to apply. Simple filters like {"name": "router1"} will be
                automatically converted to {"name__value": "router1"}.
                You can also use explicit filters :
                example: {"name__value": "router1", "tags__ids": ["tag1", "tag2"]}.
        partial_match: Whether to use partial matching for string filter

    Returns:
        Dictionary containing objects and metadata.

    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client

    msg = f"Getting nodes of kind: {kind} with filters: {filters}"
    logger.info(msg)
    # Apply filters if provided
    complete_filters = {}
    if filters:
        for key, value in filters.items():
            if "__" in key:
                # TODO: How could we check if the filter is valid ?
                complete_filters[key] = value
            elif isinstance(value, list):
                complete_filters[f"{key}__values"] = value
            else:
                complete_filters[f"{key}__value"] = value

    schema = await client.schema.get(kind=kind, branch=branch)

    try:
        if complete_filters:
            nodes = await client.filters(
                kind=schema.kind,
                branch=branch,
                partial_match=partial_match,
                parallel=True,
                order=Order(disable=True),
                # populate_store=True,
                # prefetch_relationships=True,
                **complete_filters,
            )
        else:
            nodes = await client.all(
                kind=schema.kind,
                branch=branch,
                parallel=True,
                order=Order(disable=True),
                # populate_store=True,
                # prefetch_relationships=True,
            )
    except GraphQLError as exc:
        return _log_and_return_exception(exc=exc)

    # Format the response with serializable data
    serialized_nodes = []
    for node in nodes:
        node_data = await convert_node_to_dict(branch=branch, obj=node)
        serialized_nodes.append(node_data)

    # Return the serialized response
    msg = f"Retrieved {len(serialized_nodes)} nodes of kind {schema.kind}"
    logger.info(msg)
    return {
        "success": True,
        "count": len(serialized_nodes),
        "nodes": serialized_nodes,
    }


@mcp.tool
async def infrahub_get_schemas(
    ctx: Context,
    kind: str | None = None,
    branch: str | None = None,
    exclude_profiles: bool = True,
    exclude_templates: bool = True,
) -> dict:
    """Retrieve schema information from Infrahub.

    Args:
        kind: Kind of the schema to retrieve. If None, retrieves all schemas.
        branch: Branch to retrieve the schema from. Defaults to None (uses default branch).
        exclude_profiles: Whether to exclude Profile schemas. Defaults to True.
        exclude_templates: Whether to exclude Template schemas. Defaults to True.

    Returns:
        Dictionary containing schema information.

    """
    client: InfrahubClient = ctx.request_context.lifespan_context.client

    # If kind is specified, get a specific schema
    if kind:
        msg = f"Getting schema for kind: {kind} in branch {branch or 'main'}"
        logger.info(msg)
        schema = None
        try:
            schema = await client.schema.get(kind=kind, branch=branch)
        except SchemaNotFoundError:
            msg = f"Schema not found for kind: {kind}."
            return _log_and_return_error(error=msg)

        # Create a structured response with schema details
        return {
            "success": True,
            "kind": schema.kind,
            "namespace": schema.namespace,
            "name": schema.name,
            "attributes": [
                {
                    "name": attr.name,
                    "type": attr.kind,
                    "description": attr.description,
                }
                for attr in schema.attributes
            ],
            "relationships": [
                {
                    "name": rel.name,
                    "rel_kind": rel.kind,
                    "cardinality": rel.cardinality,
                    "description": rel.description,
                }
                for rel in schema.relationships
            ],
        }

    # If kind is not specified, get all schemas for a given branch
    msg = f"Getting all schemas in branch {branch or 'main'}"
    logger.info(msg)

    all_schemas = await _get_all_schemas(
        client=client,
        branch=branch,
        exclude_profiles=exclude_profiles,
        exclude_templates=exclude_templates,
    )

    msg = f"Retrieved {len(all_schemas)} schemas"
    logger.info(msg)
    # Create a structured response with all schemas
    return {
        "success": True,
        "count": len(all_schemas),
        "schemas": [
            {
                "kind": schema.kind,
                "namespace": schema.namespace,
                "name": schema.name,
                "description": schema.description,
                "label": schema.label,
                "icon": schema.icon,
                "type": "Generic" if isinstance(schema, GenericSchemaAPI) else "Node",
                "human_friendly_id": schema.human_friendly_id,
                "uniqueness_constraints": schema.uniqueness_constraints,
                "branch_support": getattr(schema, "branch", None),
                "attributes": [
                    {
                        "name": attr.name,
                        "kind": attr.kind,
                        "description": attr.description,
                        "optional": attr.optional,
                        "unique": attr.unique,
                    }
                    for attr in schema.attributes
                ],
                "relationships": [
                    {
                        "name": rel.name,
                        "peer": rel.peer,
                        "kind": rel.kind,
                        "cardinality": rel.cardinality,
                        "description": rel.description,
                        "hierarchical": rel.hierarchical,
                    }
                    for rel in schema.relationships
                ],
                "used_by": getattr(schema, "used_by", []) if isinstance(schema, GenericSchemaAPI) else [],
                "inherit_from": getattr(schema, "inherit_from", []) if hasattr(schema, "inherit_from") else [],
            }
            for schema in all_schemas.values()
        ],
    }


@mcp.tool
async def infrahub_get_related_nodes(
    ctx: Context,
    kind: str,
    relation: str,
    filters: dict | None = None,
    branch: str | None = None,
) -> dict:
    """Fetch related nodes by relation name.

    Args:
        kind: Kind of the node to fetch.
        filters: Filters to apply on the node to fetch.
        relation: Name of the relation to fetch.
        branch: Branch to fetch the node from. Defaults to None (uses default branch).

    Returns:
        Dictionary containing the related nodes.

    """

    filters = filters or {}
    try:
        client: InfrahubClient = ctx.request_context.lifespan_context.client
        node_id = node_hfid = None
        if filters.get("ids"):
            node_id = filters["ids"][0]
        elif filters.get("hfid__value"):
            node_hfid = filters["hfid__value"]
        if node_id:
            node = await client.get(
                kind=kind,
                id=node_id,
                branch=branch,
                include=[relation],
                prefetch_relationships=True,
                populate_store=True,
            )
        elif node_hfid:
            node = await client.get(
                kind=kind,
                hfid=node_hfid,
                branch=branch,
                include=[relation],
                prefetch_relationships=True,
                populate_store=True,
            )
        else:
            return _log_and_return_error(error="No filters provided")

        rel = getattr(node, relation, None)
        if not rel:
            return {
                "success": False,
                "error": f"Relation '{relation}' not on '{kind}'",
            }
        peers = [
            await convert_node_to_dict(
                branch=branch,
                obj=peer.peer,
                include_id=True,
            )
            for peer in rel.peers
        ]
        return {
            "success": True,
            "count": len(peers),
            "nodes": peers,
        }
    except Exception as exc:  # noqa: BLE001
        return _log_and_return_error(exc)
