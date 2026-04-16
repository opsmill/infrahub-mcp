"""Schema resources for the Infrahub MCP server."""

import json
from typing import TYPE_CHECKING

import toon
from fastmcp import Context, FastMCP
from infrahub_sdk.exceptions import BranchNotFoundError, SchemaNotFoundError

from infrahub_mcp.schema import get_schema_catalog, get_schema_detail
from infrahub_mcp.utils import get_client, get_config

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient

mcp: FastMCP = FastMCP(name="Infrahub Schema Resources")


@mcp.resource(
    "infrahub://schema",
    name="Schema Catalog",
    description=(
        "All non-internal schema kinds available in this Infrahub instance, "
        "as a JSON object mapping kind names to their human-readable labels. "
        "Use this to discover what kinds exist before calling get_nodes or node_upsert."
    ),
    mime_type="application/json",
)
async def schema_catalog(ctx: Context) -> str:
    """Return the complete non-internal schema kind catalog."""
    client: InfrahubClient = get_client(ctx)  # type: ignore[assignment]

    try:
        result = await get_schema_catalog(client)
    except BranchNotFoundError as exc:
        return json.dumps({"error": str(exc)}, separators=(",", ":"))

    return json.dumps(result, separators=(",", ":"))


@mcp.resource(
    "infrahub://schema/{kind}",
    name="Schema Kind Detail",
    description=(
        "Full schema definition for a specific node kind: attributes, relationships, "
        "and the complete set of filters accepted by get_nodes. "
        "Relationships include nested peer schemas up to the server's configured "
        "INFRAHUB_MCP_MAX_QUERY_DEPTH (default 2). "
        "Arrays are encoded in TOON tabular format: "
        "header declares fields once, each row is one entry."
    ),
    mime_type="text/plain",
)
async def schema_kind_detail(kind: str, ctx: Context) -> str:
    """Return full schema definition and available filters for *kind* encoded as TOON."""
    client: InfrahubClient = get_client(ctx)  # type: ignore[assignment]
    config = get_config(ctx)

    try:
        payload = await get_schema_detail(client, kind=kind, depth=config.max_query_depth)
    except SchemaNotFoundError:
        return json.dumps(
            {
                "error": f"Schema not found for kind '{kind}'.",
                "remediation": "Read infrahub://schema to list valid kind names.",
            },
            separators=(",", ":"),
        )

    return toon.encode(payload)


@mcp.resource(
    "infrahub://graphql-schema",
    name="GraphQL Schema",
    description=(
        "Full GraphQL schema SDL for this Infrahub instance. "
        "Use as a reference when constructing complex query_graphql calls."
    ),
    mime_type="text/plain",
)
async def graphql_schema(ctx: Context) -> str:
    """Return the raw GraphQL SDL from Infrahub."""
    client: InfrahubClient = get_client(ctx)  # type: ignore[assignment]
    # infrahub_sdk has no public API to fetch the raw GraphQL SDL;
    # using private _get() as a workaround.
    # TODO: open an issue with infrahub_sdk maintainers requesting a public schema-retrieval method.
    resp = await client._get(url=f"{client.address}/schema.graphql")  # noqa: SLF001
    return resp.text
