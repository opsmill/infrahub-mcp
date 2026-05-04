"""Shared schema helpers for the Infrahub MCP server.

Both MCP resources and MCP tools import from this module to avoid
duplicating schema-fetching logic.
"""

import asyncio
from typing import TYPE_CHECKING, Any

from infrahub_sdk.exceptions import SchemaNotFoundError

from infrahub_mcp.constants import NAMESPACES_INTERNAL, schema_attribute_type_mapping
from infrahub_mcp.schema_cache import get_cached_branch_schema, get_cached_kind

if TYPE_CHECKING:
    from fastmcp import Context


async def get_schema_catalog(ctx: "Context", branch: str | None = None) -> dict[str, str]:
    """Return a kind-to-label mapping of all non-internal schema kinds."""
    branch_schema = await get_cached_branch_schema(ctx, branch=branch)
    return {
        kind: node.label or kind
        for kind, node in branch_schema.nodes.items()
        if node.namespace not in NAMESPACES_INTERNAL
    }


async def get_schema_detail(ctx: "Context", kind: str, branch: str | None = None) -> dict[str, Any]:
    """Return full schema detail for a specific kind.

    Includes attributes, relationships, and the complete filter map
    (with filters derived from related peer schemas resolved from the
    same cached BranchSchema).

    Raises:
        SchemaNotFoundError: If the kind does not exist.
    """
    schema = await get_cached_kind(ctx, kind=kind, branch=branch)

    filter_list: list[dict[str, str]] = [
        {
            "filter": f"{attr.name}__value",
            "type": schema_attribute_type_mapping.get(attr.kind, "String"),
        }
        for attr in schema.attributes
    ]

    unique_peer_kinds: list[str] = list(dict.fromkeys(rel.peer for rel in schema.relationships))

    async def _fetch_peer(peer_kind: str) -> tuple[str, Any]:
        try:
            return peer_kind, await get_cached_kind(ctx, kind=peer_kind, branch=branch)
        except SchemaNotFoundError:
            return peer_kind, None

    peer_results = await asyncio.gather(*[_fetch_peer(pk) for pk in unique_peer_kinds])
    peer_schemas: dict[str, Any] = {pk: s for pk, s in peer_results if s is not None}

    for rel in schema.relationships:
        rel_schema = peer_schemas.get(rel.peer)
        if rel_schema is None:
            continue
        filter_list.extend(
            {
                "filter": f"{rel.name}__{attr.name}__value",
                "type": schema_attribute_type_mapping.get(attr.kind, "String"),
            }
            for attr in rel_schema.attributes
        )

    return {
        "kind": schema.kind,
        "label": schema.label,
        "namespace": schema.namespace,
        "attributes": [{"name": a.name, "kind": a.kind, "optional": a.optional} for a in schema.attributes],
        "relationships": [
            {"name": r.name, "peer": r.peer, "cardinality": r.cardinality, "optional": r.optional}
            for r in schema.relationships
        ],
        "filters": filter_list,
    }


async def get_valid_kinds_summary(ctx: "Context", branch: str | None = None) -> str:
    """Return a compact string listing all valid non-internal kinds.

    Intended for inclusion in error messages so agents can self-correct
    without a second tool call.
    """
    catalog = await get_schema_catalog(ctx, branch=branch)
    return "Valid kinds: " + ", ".join(sorted(catalog.keys()))
