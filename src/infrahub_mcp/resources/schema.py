"""Schema resources for the Infrahub MCP server."""

import json

import toon
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ResourceError
from infrahub_sdk.exceptions import BranchNotFoundError, SchemaNotFoundError

from infrahub_mcp.schema import get_schema_catalog, get_schema_detail
from infrahub_mcp.utils import get_client, get_config

mcp: FastMCP = FastMCP(name="Infrahub Schema Resources")


_CATALOG_DESCRIPTION = (
    "All non-internal schema kinds available in this Infrahub instance, "
    "as a JSON object mapping kind names to their human-readable labels. "
    "Use this to discover what kinds exist before calling get_nodes or node_upsert. "
    "Same data as the get_schema() tool."
)


async def _catalog_text(ctx: Context, branch: str | None) -> str:
    client = get_client(ctx)
    try:
        result = await get_schema_catalog(client, branch=branch)
    except BranchNotFoundError as exc:
        msg = f"{exc} Call get_schema() for the default branch."
        raise ResourceError(msg) from exc
    return json.dumps(result, separators=(",", ":"))


@mcp.resource(
    "infrahub://schema",
    name="Schema Catalog",
    description=_CATALOG_DESCRIPTION + " Reads the default branch.",
    mime_type="application/json",
)
async def schema_catalog(ctx: Context) -> str:
    """Return the complete non-internal schema kind catalog of the default branch."""
    return await _catalog_text(ctx, branch=None)


@mcp.resource(
    "infrahub://schema{?branch}",
    name="Schema Catalog on Branch",
    description=_CATALOG_DESCRIPTION + " Pass ?branch=<name> to read another branch.",
    mime_type="application/json",
)
async def schema_catalog_on_branch(ctx: Context, branch: str | None = None) -> str:
    """Return the complete non-internal schema kind catalog of *branch*."""
    return await _catalog_text(ctx, branch=branch)


@mcp.resource(
    "infrahub://schema/{kind}{?branch}",
    name="Schema Kind Detail",
    description=(
        "Full schema definition for a specific node kind: attributes, relationships, "
        "and the complete set of filters accepted by get_nodes. "
        "Relationships include one level of inlined peer schemas when "
        "INFRAHUB_MCP_SCHEMA_EXPAND_PEERS is enabled (the default). "
        "Pass ?branch=<name> to read another branch than the default one. "
        "Same data as get_schema(kind=...). "
        "Arrays are encoded in TOON tabular format: "
        "header declares fields once, each row is one entry."
    ),
    mime_type="text/plain",
)
async def schema_kind_detail(kind: str, ctx: Context, branch: str | None = None) -> str:
    """Return full schema definition and available filters for *kind* on *branch*, encoded as TOON."""
    client = get_client(ctx)
    config = get_config(ctx)

    try:
        payload = await get_schema_detail(client, kind=kind, branch=branch, expand_peers=config.schema_expand_peers)
    except SchemaNotFoundError as exc:
        msg = f"Schema not found for kind '{kind}'. Call get_schema() to list valid kind names."
        raise ResourceError(msg) from exc
    except BranchNotFoundError as exc:
        msg = f"{exc} Call get_schema() for the default branch."
        raise ResourceError(msg) from exc

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
    client = get_client(ctx)
    # infrahub_sdk has no public API to fetch the raw GraphQL SDL;
    # using private _get() as a workaround.
    # TODO: open an issue with infrahub_sdk maintainers requesting a public schema-retrieval method.
    resp = await client._get(url=f"{client.address}/schema.graphql")  # noqa: SLF001  # pylint: disable=protected-access
    return resp.text
