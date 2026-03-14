import json
from typing import TYPE_CHECKING, Any

import toon
from fastmcp import Context, FastMCP
from infrahub_sdk.exceptions import BranchNotFoundError, SchemaNotFoundError

from infrahub_mcp.constants import NAMESPACES_INTERNAL, schema_attribute_type_mapping

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
    client: InfrahubClient = ctx.request_context.lifespan_context.client  # type: ignore[assignment]

    try:
        all_schemas = await client.schema.all()
    except BranchNotFoundError as exc:
        return json.dumps({"error": str(exc)}, separators=(",", ":"))

    result = {
        kind: node.label or kind
        for kind, node in all_schemas.items()
        if node.namespace not in NAMESPACES_INTERNAL
    }
    return json.dumps(result, separators=(",", ":"))


@mcp.resource(
    "infrahub://schema/{kind}",
    name="Schema Kind Detail",
    description=(
        "Full schema definition for a specific node kind: attributes, relationships, "
        "and the complete set of filters accepted by get_nodes. "
        "Fetch this before filtering nodes of an unfamiliar kind. "
        "Arrays are encoded in TOON tabular format: header declares fields once, each row is one entry."
    ),
    mime_type="text/plain",
)
async def schema_kind_detail(kind: str, ctx: Context) -> str:
    """Return full schema definition and available filters for *kind* encoded as TOON."""
    client: InfrahubClient = ctx.request_context.lifespan_context.client  # type: ignore[assignment]

    try:
        schema = await client.schema.get(kind=kind)
    except SchemaNotFoundError:
        return json.dumps(
            {
                "error": f"Schema not found for kind '{kind}'.",
                "remediation": "Read infrahub://schema to list valid kind names.",
            },
            separators=(",", ":"),
        )

    # Build filters as list-of-dicts so TOON can tabularise them
    filter_list: list[dict[str, str]] = [
        {"filter": f"{attr.name}__value", "type": schema_attribute_type_mapping.get(attr.kind, "String")}
        for attr in schema.attributes
    ]
    for rel in schema.relationships:
        try:
            rel_schema = await client.schema.get(kind=rel.peer)
        except SchemaNotFoundError:
            continue
        filter_list.extend(
            {
                "filter": f"{rel.name}__{attr.name}__value",
                "type": schema_attribute_type_mapping.get(attr.kind, "String"),
            }
            for attr in rel_schema.attributes
        )

    payload: dict[str, Any] = {
        "kind": schema.kind,
        "label": schema.label,
        "namespace": schema.namespace,
        "attributes": [
            {"name": a.name, "kind": a.kind, "optional": a.optional}
            for a in schema.attributes
        ],
        "relationships": [
            {"name": r.name, "peer": r.peer, "cardinality": r.cardinality, "optional": r.optional}
            for r in schema.relationships
        ],
        "filters": filter_list,
    }
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
    client: InfrahubClient = ctx.request_context.lifespan_context.client  # type: ignore[assignment]
    resp = await client._get(url=f"{client.address}/schema.graphql")  # noqa: SLF001
    return resp.text
