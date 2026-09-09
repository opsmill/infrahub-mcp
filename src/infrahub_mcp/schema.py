"""Shared schema helpers for the Infrahub MCP server.

Both MCP resources and MCP tools import from this module to avoid
duplicating schema-fetching logic.
"""

import asyncio
from typing import TYPE_CHECKING, Any

from infrahub_sdk.exceptions import SchemaNotFoundError

from infrahub_mcp.constants import NAMESPACES_INTERNAL, schema_attribute_type_mapping
from infrahub_mcp.schema_cache import get_cached_branch_schema, get_cached_kind
from infrahub_mcp.utils import get_client

if TYPE_CHECKING:
    from fastmcp import Context
    from infrahub_sdk.client import InfrahubClient


async def get_schema_catalog(
    ctx: "Context",
    branch: str | None = None,
    *,
    client: "InfrahubClient | None" = None,
) -> dict[str, str]:
    """Return a kind-to-label mapping of all non-internal schema kinds.

    *client* is the client the schema read goes through; when omitted, one is
    resolved here, once. A caller that already holds this request's client
    passes it so the read reuses a credential Infrahub has already checked
    instead of probing again — in the passthrough modes every unprimed client
    costs one ``/summary`` probe (see
    :func:`~infrahub_mcp.schema_cache.get_cached_branch_schema`).
    """
    client = client if client is not None else get_client(ctx)
    branch_schema = await get_cached_branch_schema(ctx, branch=branch, client=client)
    return {
        kind: node.label or kind
        for kind, node in branch_schema.nodes.items()
        if node.namespace not in NAMESPACES_INTERNAL
    }


def _shape_attribute(attr: Any) -> dict[str, Any]:
    """Compact attribute shape, used identically for root and peer schemas."""
    return {"name": attr.name, "kind": attr.kind, "optional": attr.optional}


def _shape_relationship(rel: Any) -> dict[str, Any]:
    """Compact relationship shape, used identically for root and peer schemas."""
    return {"name": rel.name, "peer": rel.peer, "cardinality": rel.cardinality, "optional": rel.optional}


def _build_peer_schema(peer: Any) -> dict[str, Any]:
    """Build a one-level peer schema dict (no filters, no nested expansion)."""
    return {
        "kind": peer.kind,
        "label": peer.label,
        "namespace": peer.namespace,
        "attributes": [_shape_attribute(a) for a in peer.attributes],
        "relationships": [_shape_relationship(r) for r in peer.relationships],
    }


async def get_schema_detail(
    ctx: "Context",
    kind: str,
    branch: str | None = None,
    expand_peers: bool = True,
    *,
    client: "InfrahubClient | None" = None,
) -> dict[str, Any]:
    """Return full schema detail for a specific kind.

    Includes attributes, relationships, and the complete filter map
    (with filters derived from related peer schemas resolved from the
    same cached BranchSchema).

    When ``expand_peers`` is ``True``, each relationship whose peer kind exists
    includes a ``peer_schema`` key holding that peer's attributes and
    relationships, inlined a single level deep. Peer schemas omit filters and
    are not expanded further (their relationships stay as plain peer references).

    One client serves the whole call — the kind itself and every peer it
    gathers — so a request validates its credential against Infrahub once,
    not once per peer; see :func:`get_schema_catalog` for *client*.

    Args:
        ctx: FastMCP request context.
        kind: Schema kind to retrieve.
        branch: Optional branch to query.
        expand_peers: Inline one level of peer schemas on relationships.
        client: Client the schema reads go through; resolved once here when omitted.

    Returns:
        Dict with keys: kind, label, namespace, attributes, relationships, filters.

    Raises:
        SchemaNotFoundError: If the kind does not exist.
    """
    client = client if client is not None else get_client(ctx)
    schema = await get_cached_kind(ctx, kind=kind, branch=branch, client=client)

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
            return peer_kind, await get_cached_kind(ctx, kind=peer_kind, branch=branch, client=client)
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

    relationships: list[dict[str, Any]] = []
    for rel in schema.relationships:
        rel_dict = _shape_relationship(rel)
        if expand_peers and rel.peer in peer_schemas:
            rel_dict["peer_schema"] = _build_peer_schema(peer_schemas[rel.peer])
        relationships.append(rel_dict)

    return {
        "kind": schema.kind,
        "label": schema.label,
        "namespace": schema.namespace,
        "attributes": [_shape_attribute(a) for a in schema.attributes],
        "relationships": relationships,
        "filters": filter_list,
    }


async def get_valid_kinds_summary(
    ctx: "Context",
    branch: str | None = None,
    *,
    client: "InfrahubClient | None" = None,
) -> str:
    """Return a compact string listing all valid non-internal kinds.

    Intended for inclusion in error messages so agents can self-correct
    without a second tool call. Tools call it after a ``SchemaNotFoundError``
    from a read on their own client; passing that *client* keeps the error
    path from probing Infrahub a second time (see :func:`get_schema_catalog`).
    """
    catalog = await get_schema_catalog(ctx, branch=branch, client=client)
    return "Valid kinds: " + ", ".join(sorted(catalog.keys()))
