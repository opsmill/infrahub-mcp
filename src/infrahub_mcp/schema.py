"""Shared schema helpers for the Infrahub MCP server.

Both MCP resources and MCP tools import from this module to avoid
duplicating schema-fetching logic.
"""

import asyncio
from typing import TYPE_CHECKING, Any

from infrahub_sdk.exceptions import SchemaNotFoundError

from infrahub_mcp.constants import NAMESPACES_INTERNAL, schema_attribute_type_mapping

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient


async def get_schema_catalog(client: "InfrahubClient", branch: str | None = None) -> dict[str, str]:
    """Return a kind-to-label mapping of all non-internal schema kinds.

    Args:
        client: Infrahub SDK client.
        branch: Optional branch to query. Defaults to the default branch.

    Returns:
        Dict mapping kind names to human-readable labels.
    """
    all_schemas = await client.schema.all(branch=branch)
    return {kind: node.label or kind for kind, node in all_schemas.items() if node.namespace not in NAMESPACES_INTERNAL}


def _peer_rel_filters(
    relationships: Any,
    peer_schemas: dict[str, Any],
) -> list[dict[str, str]]:
    """Build filter entries contributed by peer-schema attributes.

    Args:
        relationships: Iterable of relationship objects.
        peer_schemas: Mapping of peer kind to its raw schema node.

    Returns:
        List of filter dicts (``{"filter": ..., "type": ...}``).
    """
    result: list[dict[str, str]] = []
    for rel in relationships:
        rel_schema = peer_schemas.get(rel.peer)
        if rel_schema is None:
            continue
        result.extend(
            {
                "filter": f"{rel.name}__{attr.name}__value",
                "type": schema_attribute_type_mapping.get(attr.kind, "String"),
            }
            for attr in rel_schema.attributes
        )
    return result


async def _expand_peer_schemas(  # noqa: PLR0913, PLR0917
    client: "InfrahubClient",
    relationships: Any,
    visited: set[str],
    branch: str | None,
    depth: int,
    seen_kinds: set[str],
) -> dict[str, dict[str, Any]]:
    """Fetch expanded schema details for all unvisited peer kinds in parallel.

    Args:
        client: Infrahub SDK client.
        relationships: Iterable of relationship objects with a ``.peer`` attribute.
        visited: Kinds already on the current traversal path.
        branch: Optional branch to query.
        depth: Remaining expansion depth (already decremented by caller).
        seen_kinds: Globally shared set of kinds already fully expanded
            (used for deduplication across branches).

    Returns:
        Mapping of peer kind to its expanded schema detail dict.
    """
    expandable_peers: list[str] = list(
        dict.fromkeys(
            rel.peer for rel in relationships if rel.peer not in visited and rel.peer not in seen_kinds
        )
    )

    async def _expand_one(peer_kind: str) -> tuple[str, dict[str, Any] | None]:
        if peer_kind in seen_kinds:
            return peer_kind, None
        return peer_kind, await get_schema_detail(
            client,
            kind=peer_kind,
            branch=branch,
            depth=depth,
            _visited=set(visited),
            _include_filters=False,
            _seen_kinds=seen_kinds,
        )

    expanded = await asyncio.gather(*[_expand_one(pk) for pk in expandable_peers])
    return {pk: detail for pk, detail in expanded if detail is not None}


async def get_schema_detail(  # noqa: C901
    client: "InfrahubClient",
    kind: str,
    branch: str | None = None,
    depth: int = 0,
    _visited: set[str] | None = None,
    _include_filters: bool = True,
    _seen_kinds: set[str] | None = None,
) -> dict[str, Any]:
    """Return full schema detail for a specific kind.

    Includes attributes, relationships, and the complete filter map
    (with filters derived from related peer schemas fetched in parallel).

    When ``depth`` > 0, each relationship includes a ``peer_schema`` key
    containing the full schema of the related kind, recursively expanded
    up to ``depth`` levels. Cycles are detected per traversal path and
    marked with ``"_seen": True`` instead of ``peer_schema``.

    Nested peer schemas omit filters to reduce token usage. Kinds that
    have already been fully expanded elsewhere in the response are
    referenced as ``"peer_schema": "@ref:<KindName>"`` instead of being
    repeated.

    Args:
        client: Infrahub SDK client.
        kind: Schema kind to retrieve.
        branch: Optional branch to query.
        depth: Relationship traversal depth (0 = no expansion). Negative
            values are normalized to 0.
        _visited: Kinds already expanded in the current traversal path.
            Callers should not set this — it is managed by recursion.
        _include_filters: Whether to include the filters key in the result.
            Set to ``False`` for nested peer schemas to save tokens.
        _seen_kinds: Globally shared set of kinds already fully expanded.
            Used for deduplication — subsequent occurrences of the same kind
            are replaced with ``"@ref:<KindName>"``.

    Returns:
        Dict with keys: kind, label, namespace, attributes, relationships,
        and optionally filters (only at the root level).

    Raises:
        SchemaNotFoundError: If the kind does not exist.
    """
    depth = max(depth, 0)
    if _visited is None:
        _visited = set()
    if _seen_kinds is None:
        _seen_kinds = set()

    schema = await client.schema.get(kind=kind, branch=branch)

    filter_list: list[dict[str, str]] = []
    if _include_filters:
        filter_list = [
            {
                "filter": f"{attr.name}__value",
                "type": schema_attribute_type_mapping.get(attr.kind, "String"),
            }
            for attr in schema.attributes
        ]

        unique_peer_kinds: list[str] = list(dict.fromkeys(rel.peer for rel in schema.relationships))

        async def _fetch_peer(peer_kind: str) -> tuple[str, Any]:
            try:
                return peer_kind, await client.schema.get(kind=peer_kind, branch=branch)
            except SchemaNotFoundError:
                return peer_kind, None

        peer_results = await asyncio.gather(*[_fetch_peer(pk) for pk in unique_peer_kinds])
        peer_schemas: dict[str, Any] = {pk: s for pk, s in peer_results if s is not None}

        filter_list.extend(_peer_rel_filters(schema.relationships, peer_schemas))

    # Build relationship dicts with optional depth expansion
    _visited.add(kind)
    peer_detail_map: dict[str, dict[str, Any]] = {}
    if depth > 0:
        peers_to_expand = [
            rel.peer for rel in schema.relationships
            if rel.peer not in _visited and rel.peer not in _seen_kinds
        ]
        unique_to_expand: list[str] = list(dict.fromkeys(peers_to_expand))
        if unique_to_expand:
            peer_detail_map = await _expand_peer_schemas(
                client, schema.relationships, _visited, branch, depth - 1, _seen_kinds,
            )

    relationships: list[dict[str, Any]] = []
    for rel in schema.relationships:
        rel_dict: dict[str, Any] = {
            "name": rel.name,
            "peer": rel.peer,
            "cardinality": rel.cardinality,
            "optional": rel.optional,
        }
        if depth > 0:
            if rel.peer in _visited:
                rel_dict["_seen"] = True
            elif rel.peer in peer_detail_map:
                rel_dict["peer_schema"] = peer_detail_map[rel.peer]
            elif rel.peer in _seen_kinds:
                rel_dict["peer_schema"] = f"@ref:{rel.peer}"
        relationships.append(rel_dict)

    _visited.discard(kind)

    result: dict[str, Any] = {
        "kind": schema.kind,
        "label": schema.label,
        "namespace": schema.namespace,
        "attributes": [{"name": a.name, "kind": a.kind, "optional": a.optional} for a in schema.attributes],
        "relationships": relationships,
    }
    if _include_filters:
        result["filters"] = filter_list
    _seen_kinds.add(kind)
    return result


async def get_valid_kinds_summary(client: "InfrahubClient", branch: str | None = None) -> str:
    """Return a compact string listing all valid non-internal kinds.

    Intended for inclusion in error messages so agents can self-correct
    without a second tool call.

    Args:
        client: Infrahub SDK client.
        branch: Optional branch to query.

    Returns:
        String like "Valid kinds: InfraDevice, InfraInterfaceL3, ..."
    """
    catalog = await get_schema_catalog(client, branch=branch)
    return "Valid kinds: " + ", ".join(sorted(catalog.keys()))
