from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastmcp import FastMCP
from infrahub_sdk import Config, InfrahubClient
from infrahub_sdk.exceptions import GraphQLError, SchemaNotFoundError
from infrahub_sdk.node import Attribute, InfrahubNode, RelatedNode, RelationshipManager
from infrahub_sdk.schema.main import GenericSchemaAPI, NodeSchemaAPI
from infrahub_sdk.types import Order

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("infrahub_mcp")

# Initialize FastAPI app
app = FastAPI(title="Infrahub MCP Server")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize the FastMCP application
mcp = FastMCP("Infrahub", log_level="DEBUG")


async def _convert_node_to_dict(*, obj: InfrahubNode, include_id: bool = True) -> dict[str, Any]:
    data = {}

    if include_id:
        data["index"] = obj.id or None

    for attr_name in obj._schema.attribute_names:  # noqa: SLF001
        attr: Attribute = getattr(obj, attr_name)
        data[attr_name] = attr.value

    for rel_name in obj._schema.relationship_names:  # noqa: SLF001
        rel = getattr(obj, rel_name)
        if rel and isinstance(rel, RelatedNode):
            if rel.initialized:
                await rel.fetch()
                related_node = obj._client.store.get(key=rel.peer.id, raise_when_missing=False)  # noqa: SLF001
                data[rel_name] = (
                    related_node.get_human_friendly_id_as_string(include_kind=True)
                    if related_node.hfid
                    else related_node.id
                )
        elif rel and isinstance(rel, RelationshipManager):
            peers: list[dict[str, Any]] = []
            if not rel.initialized:
                await rel.fetch()
            for peer in rel.peers:
                # FIXME: We are using the store to avoid doing to many queries to Infrahub
                # but we could end up doing store+infrahub if the store is not populated
                related_node = obj._client.store.get(key=peer.id, raise_when_missing=False)  # noqa: SLF001
                if not related_node:
                    await peer.fetch()
                    related_node = peer.peer
                peers.append(
                    related_node.get_human_friendly_id_as_string(include_kind=True)
                    if related_node.hfid
                    else related_node.id,
                )
            data[rel_name] = peers
    return data


async def _get_all_schemas(
    *,
    infrahub_client: InfrahubClient,
    branch: str | None = None,
    exclude_profiles: bool | None = True,
    exclude_templates: bool | None = True,
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
    all_schemas = await infrahub_client.schema.all(branch=branch)

    # Filter out Profile and Template if requested
    filtered_schemas = {}
    for kind, schema in all_schemas.items():
        if exclude_templates and schema.kind.startswith("Template"):
            continue
        if exclude_profiles and schema.kind.startswith("Profile"):
            continue
        filtered_schemas[kind] = schema

    return filtered_schemas


async def _find_similar_kinds(
    *,
    infrahub_client: InfrahubClient,
    kind: str,
    branch: str | None = None,
    exclude_profiles: bool | None = True,
    exclude_templates: bool | None = True,
) -> list[str]:
    """Find similar schema kinds for a given kind string.

    Args:
        infrahub_client: Infrahub client to use
        kind: The kind string to find similar kinds for
        branch: Branch to search in
        exclude_profiles: Whether to exclude Profile schemas
        exclude_templates: Whether to exclude template schemas

    Returns:
        List of similar kind strings

    """
    # Get all schemas
    all_schemas = await _get_all_schemas(
        infrahub_client=infrahub_client,
        branch=branch,
        exclude_profiles=exclude_profiles,
        exclude_templates=exclude_templates,
    )

    kind_lower = kind.lower()

    # Check if the requested kind is a substring of an existing kind or vice versa
    return [
        other_schema.kind
        for other_schema in all_schemas.values()
        if kind_lower in other_schema.kind.lower() or other_schema.kind.lower() in kind_lower
    ]


@mcp.tool()
async def infrahub_get_nodes(
    *,
    kind: str,
    branch: str | None = None,
    filters: dict | None = None,
    partial_match: bool = False,
    infrahub_url: str | None = None,
    infrahub_api_token: str | None = None,
) -> dict:
    """Retrieve objects from Infrahub.

    Args:
        infrahub_client: Infrahub client to use
        kind: Kind of the objects to retrieve.
        branch: Branch to retrieve the objects from. Defaults to None (uses default branch).
        filters: Dictionary of filters to apply. Simple filters like {"name": "router1"} will be
                automatically converted to {"name__value": "router1"}.
                You can also use explicit filters :
                example: {"name__value": "router1", "tags__ids": ["tag1", "tag2"]}.
        partial_match: Whether to use partial matching for string filter
        infrahub_url: URL of the Infrahub instance. Defaults to None (uses environment variable).
        infrahub_api_token: API token for Infrahub. Defaults to None (uses environment variable).

    Returns:
        Dictionary containing objects and metadata.

    """
    infrahub_client = await initialize_client(infrahub_url=infrahub_url, infrahub_api_token=infrahub_api_token)
    logger.info(f"Getting nodes of kind: {kind} with filters: {filters}")
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

    try:
        schema = await infrahub_client.schema.get(kind=kind, branch=branch)
    except SchemaNotFoundError as exc:
        # Find similar kinds
        similar_kinds = await _find_similar_kinds(infrahub_client=infrahub_client, kind=kind, branch=branch)
        if len(similar_kinds) == 1:
            msg = f"Using similar kind: {similar_kinds[0]} instead of {kind}"
            logger.info(msg)
            schema = await infrahub_client.schema.get(kind=similar_kinds[0], branch=branch)
        else:
            msg = f"Schema not found for kind: {kind}. Similar kinds: {similar_kinds}"
            logger.warning(msg)
            return {
                "success": False,
                "error": str(exc),
                "similar_kinds": similar_kinds,
            }

    if complete_filters:
        try:
            nodes = await infrahub_client.filters(
                kind=schema.kind,
                branch=branch,
                partial_match=partial_match,
                parallel=True,
                order=Order(disable=True),
                # populate_store=True,
                # prefetch_relationships=True,
                **complete_filters,
            )
        except GraphQLError as exc:
            msg = f"GraphQL error when filtering {schema.kind}: {exc}"
            logger.exception(msg)
            return {
                "success": False,
                "error": str(exc),
            }
    else:
        nodes = await infrahub_client.all(
            kind=schema.kind,
            branch=branch,
            parallel=True,
            order=Order(disable=True),
            # populate_store=True,
            # prefetch_relationships=True,
        )

    logger.info(msg)
    # Format the response with serializable data
    serialized_nodes = []
    for node in nodes:
        node_data = await _convert_node_to_dict(obj=node)
        serialized_nodes.append(node_data)

    # Return the serialized response
    msg = f"Retrieved {len(serialized_nodes)} nodes of kind {schema.kind}"
    return {
        "success": True,
        "count": len(serialized_nodes),
        "nodes": serialized_nodes,
    }


@mcp.tool()
async def infrahub_get_schema(  # noqa: PLR0913
    *,
    kind: str | None = None,
    branch: str | None = None,
    exclude_profiles: bool | None = True,
    exclude_templates: bool | None = True,
    infrahub_url: str | None = None,
    infrahub_api_token: str | None = None,
) -> dict:
    """Retrieve schema information from Infrahub.

    Args:
        kind: Kind of the schema to retrieve. If None, retrieves all schemas.
        branch: Branch to retrieve the schema from. Defaults to None (uses default branch).
        exclude_profiles: Whether to exclude Profile schemas. Defaults to True.
        exclude_templates: Whether to exclude Template schemas. Defaults to True.
        infrahub_url: URL of the Infrahub instance. Defaults to None (uses environment variable).
        infrahub_api_token: API token for Infrahub. Defaults to None (uses environment variable).

    Returns:
        Dictionary containing schema information.

    """
    infrahub_client = await initialize_client(infrahub_url=infrahub_url, infrahub_api_token=infrahub_api_token)
    # If kind is specified, get a specific schema
    if kind:
        msg = f"Getting schema for kind: {kind} in branch {branch or 'main'}"
        logger.info(msg)
        schema = None
        try:
            schema = await infrahub_client.schema.get(kind=kind, branch=branch)
        except SchemaNotFoundError as exc:
            # Find similar kinds
            similar_kinds = await _find_similar_kinds(
                infrahub_client=infrahub_client,
                kind=kind,
                branch=branch,
                exclude_profiles=exclude_profiles,
            )

            if len(similar_kinds) == 1:
                # If there's exactly one similar kind, use it
                msg = f"Using similar kind: {similar_kinds[0]} instead of {kind}"
                logger.info(msg)
                schema = await infrahub_client.schema.get(kind=similar_kinds[0], branch=branch)
            else:
                msg = f"Schema not found for kind: {kind}. Similar kinds: {similar_kinds}"
                logger.warning(msg)
                return {
                    "success": False,
                    "error": str(exc),
                    "similar_kinds": similar_kinds,
                }

        # Create a structured response with schema details
        if not schema:
            return {
                "success": False,
            }
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
        infrahub_client=infrahub_client,
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


# Add route for MCP requests
@app.post("/")
async def handle_mcp_request(request: Request) -> dict:
    """Handle MCP requests.

    Returns:
        Dictionary containing the result of the MCP request.

    """
    data = await request.json()
    tool_name = data.get("tool")
    params = data.get("params", {})

    msg = f"Received MCP request for tool: {tool_name}"
    logger.info(msg)

    # Map tool names to functions
    tool_map = {
        "infrahub_get_nodes": infrahub_get_nodes,
        "infrahub_get_schema": infrahub_get_schema,
    }

    if tool_name in tool_map:
        try:
            result = await tool_map[tool_name](**params)
            return {"result": result}  # noqa: TRY300

        except Exception as e:
            msg = f"Error executing tool {tool_name}: {e}"
            logger.exception(msg)
            return {"error": f"Error executing tool {tool_name}: {e!s}"}

    msg = f"Unknown tool: {tool_name}"
    logger.warning(msg)
    return {"error": f"Unknown tool: {tool_name}"}


def handle_tools_discover() -> dict[str, Any]:
    """Handle tools/discover method for JSON-RPC interface.

    Returns:
        Dictionary containing the result of the tools/discover request.

    """
    tools = [
        {
            "name": "infrahub_get_nodes",
            "description": infrahub_get_nodes.__doc__.strip() if infrahub_get_nodes.__doc__ else "",
            "parameters": {
                "type": "object",
                "properties": {
                    "infrahub_url": {
                        "type": "string",
                        "description": "URL of the Infrahub instance. Defaults to None (uses environment variable).",
                    },
                    "infrahub_api_token": {
                        "type": "string",
                        "description": "API token for Infrahub. Defaults to None (uses environment variable).",
                    },
                    "kind": {"type": "string", "description": "Kind of the objects to retrieve."},
                    "branch": {"type": "string", "description": "Branch to retrieve the objects from."},
                    "filters": {"type": "object", "description": "Dictionary of filters to apply."},
                    "partial_match": {
                        "type": "boolean",
                        "description": "Whether to use partial matching for string filter.",
                    },
                },
                "required": ["kind"],
            },
        },
        {
            "name": "infrahub_get_schema",
            "description": infrahub_get_schema.__doc__.strip() if infrahub_get_schema.__doc__ else "",
            "parameters": {
                "type": "object",
                "properties": {
                    "infrahub_url": {
                        "type": "string",
                        "description": "URL of the Infrahub instance. Defaults to None (uses environment variable).",
                    },
                    "infrahub_api_token": {
                        "type": "string",
                        "description": "API token for Infrahub. Defaults to None (uses environment variable).",
                    },
                    "kind": {
                        "type": "string",
                        "description": "Kind of the schema to retrieve. If None, retrieves all schemas.",
                    },
                    "branch": {"type": "string", "description": "Branch to retrieve the schema from."},
                    "exclude_profiles": {"type": "boolean", "description": "Whether to exclude Profile schemas."},
                    "exclude_templates": {"type": "boolean", "description": "Whether to exclude Template schemas."},
                },
            },
        },
    ]
    return {"result": tools}


async def handle_tools_call(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Handle tools/call method for JSON-RPC interface.

    Returns:
        Dictionary containing the result of the tools/call request.

    """
    tool_map = {
        "infrahub_get_nodes": infrahub_get_nodes,
        "infrahub_get_schema": infrahub_get_schema,
    }

    if tool_name in tool_map:
        try:
            result = await tool_map[tool_name](**arguments)
            return {"result": result}

        except Exception as e:
            msg = f"Error executing tool {tool_name}: {e}"
            logger.exception(msg)
            return {"error": f"Error executing tool {tool_name}: {e!s}"}

    return {"error": f"Unknown tool: {tool_name}"}


async def monitor_stdin() -> None:
    """Monitor stdin for JSON-RPC requests."""
    logger.info("Starting stdin monitor for JSON-RPC requests")
    loop = asyncio.get_event_loop()

    try:
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            line = line.strip()
            if not line:
                await asyncio.sleep(0.1)
                continue

            msg = f"Read from stdin: {line}"
            logger.info(msg)

            try:
                data = json.loads(line)
            except json.JSONDecodeError as e:
                msg = f"JSON decode error: {e}"
                logger.exception(msg)
                await send_response({"error": f"Invalid JSON input: {e}"})
                continue

            if not isinstance(data, dict):
                msg = f"Invalid input: {data}. Expected a JSON object."
                logger.error(msg)
                await send_response({"error": "Invalid input: Expected a JSON object."})
                continue

            method = data.get("method")
            params = data.get("params", {})
            msg = f"Method: {method}, Params: {params}"
            logger.info(msg)

            if method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                response = await handle_tools_call(tool_name, arguments)
                await send_response(response)
            elif method == "tools/discover":
                response = handle_tools_discover()
                await send_response(response)
            else:
                error_msg = f"Unknown method: {method}"
                logger.warning(error_msg)
                await send_response({"error": error_msg})
    except Exception as e:
        msg = f"Exception in monitor_stdin: {e}"
        logger.exception(msg)


async def send_response(response_data: dict) -> None:
    """Send JSON-RPC response to stdout."""
    response = json.dumps(response_data) + "\n"
    sys.stdout.write(response)
    sys.stdout.flush()
    msg = f"Sent response: {response.strip()}"
    logger.info(msg)


async def initialize_client(infrahub_url: str | None = None, infrahub_api_token: str | None = None) -> InfrahubClient:
    """Initialize the Infrahub client.

    Args:
        infrahub_url: URL of the Infrahub instance. Defaults to None (uses environment variable).
        infrahub_api_token: API token for Infrahub. Defaults to None (uses environment variable).

    Returns:
        InfrahubClient: Initialized Infrahub client

    """
    infrahub_url = infrahub_url or os.getenv("INFRAHUB_URL", "http://localhost:8000")
    infrahub_api_token = infrahub_api_token or os.getenv("INFRAHUB_API_TOKEN", "06438eb2-8019-4776-878c-0941b1f1d1ec")

    # Initialize the client
    config = Config(
        address=infrahub_url,
        api_token=infrahub_api_token,
    )

    infrahub_client = InfrahubClient(config=config)
    msg = f"Initialized Infrahub client with URL: {infrahub_url}"
    logger.info(msg)

    # Test connection
    try:
        await infrahub_client.get_version()
        logger.info("Successfully connected to Infrahub")
    except Exception as e:
        msg = f"Failed to connect to Infrahub: {e}"
        logger.exception(msg)
        raise
    return infrahub_client


def run_web_server() -> None:
    """Run the FastAPI web server."""
    import uvicorn  # noqa: PLC0415

    port = int(os.getenv("MCP_PORT", "8001"))
    host = os.getenv("MCP_HOST", "0.0.0.0")  # noqa: S104
    msg = f"Starting web server on {host}:{port}"
    logger.info(msg)
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    logger.info("Starting Infrahub MCP server")

    # Check if we're in oneshot mode
    if "--oneshot" in sys.argv:
        logger.info("Running in oneshot mode")
        line = sys.stdin.readline().strip()
        try:
            data = json.loads(line)
            method = data.get("method")
            params = data.get("params", {})

            if method == "tools/discover":
                result = handle_tools_discover()
                asyncio.run(send_response(result))
            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                result = asyncio.run(handle_tools_call(tool_name, arguments))
                asyncio.run(send_response(result))
            else:
                asyncio.run(send_response({"error": f"Unknown method: {method}"}))
        except Exception as e:
            msg = f"Error in oneshot mode: {e}"
            logger.exception(msg)
            asyncio.run(send_response({"error": str(e)}))
        sys.exit(0)

    # Check if we should run in web mode or stdin mode
    if "--web" in sys.argv:
        # Initialize client and run web server
        run_web_server()
    else:
        # Run in stdin/stdout mode
        asyncio.run(monitor_stdin())
