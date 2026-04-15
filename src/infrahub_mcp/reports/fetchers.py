"""Pure data-fetching functions for the analytics reports module.

All functions in this module call the Infrahub SDK and return plain
dicts/lists. They have no dependency on prefab_ui or any UI layer.
"""

from __future__ import annotations

import asyncio
import operator
from collections import Counter
from typing import TYPE_CHECKING, Any

from infrahub_mcp.utils import convert_node_to_dict

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from infrahub_sdk.client import InfrahubClient


async def fetch_schema_catalog(
    client: InfrahubClient, branch: str | None = None
) -> list[dict[str, Any]]:
    """Fetch all concrete kinds from the schema.

    Args:
        client: Infrahub SDK client.
        branch: Optional branch to query. Defaults to the default branch.

    Returns:
        List of dicts with keys: kind, namespace, label, attr_count, rel_count.
    """
    all_schemas = await client.schema.all(branch=branch)
    result: list[dict[str, Any]] = []
    for kind, schema_obj in all_schemas.items():
        result.append(
            {
                "kind": kind,
                "namespace": schema_obj.namespace,
                "label": schema_obj.label or kind,
                "attr_count": len(schema_obj.attributes),
                "rel_count": len(schema_obj.relationships),
            }
        )
    return result


async def fetch_schema_detail(
    client: InfrahubClient, kind: str, branch: str | None = None
) -> dict[str, Any]:
    """Fetch detailed schema for a specific kind.

    Args:
        client: Infrahub SDK client.
        kind: The schema kind to retrieve.
        branch: Optional branch to query.

    Returns:
        Dict with keys: kind, attributes (list of attr dicts), relationships (list of rel dicts).
        Each attribute dict has: name, kind (e.g. "Text", "Dropdown", "Number"), optional (bool).
        Each relationship dict has: name, peer, cardinality ("one" or "many").
    """
    schema = await client.schema.get(kind=kind, branch=branch)
    return {
        "kind": schema.kind,
        "attributes": [
            {"name": attr.name, "kind": attr.kind, "optional": attr.optional}
            for attr in schema.attributes
        ],
        "relationships": [
            {"name": rel.name, "peer": rel.peer, "cardinality": rel.cardinality}
            for rel in schema.relationships
        ],
    }


async def fetch_nodes_for_kind(
    client: InfrahubClient, kind: str, branch: str | None = None, limit: int = 200
) -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch nodes of a given kind, return (rows, column_names).

    Args:
        client: Infrahub SDK client.
        kind: The schema kind to query.
        branch: Optional branch to query.
        limit: Maximum number of nodes to retrieve. Defaults to 200.

    Returns:
        Tuple of (rows, column_names) where each row is a dict mapping
        column names to string values, and column_names are derived from
        the schema (attribute names + relationship names).
    """
    schema = await client.schema.get(kind=kind, branch=branch)
    column_names: list[str] = [attr.name for attr in schema.attributes] + [
        rel.name for rel in schema.relationships
    ]

    nodes = await client.all(kind=kind, branch=branch, limit=limit)
    rows: list[dict[str, Any]] = []
    for node in nodes:
        row = await convert_node_to_dict(obj=node, branch=branch)
        rows.append(row)

    return rows, column_names


async def fetch_node_counts(
    client: InfrahubClient,
    kinds: list[str],
    branch: str | None = None,
    concurrency: int = 10,
    on_progress: Callable[[int, int], Awaitable[None]] | None = None,
) -> list[dict[str, Any]]:
    """Fetch node count for each kind concurrently.

    Args:
        client: Infrahub SDK client.
        kinds: List of schema kinds to count.
        branch: Optional branch to query.
        concurrency: Maximum number of parallel queries. Defaults to 10.
        on_progress: Optional async callback called as on_progress(done, total)
            after each kind completes.

    Returns:
        List of dicts with keys: kind, label, count. Sorted by count descending.
    """
    total = len(kinds)
    semaphore = asyncio.Semaphore(concurrency)
    done_counter: list[int] = [0]

    # Build a label map from the schema catalog upfront
    all_schemas = await client.schema.all(branch=branch)
    label_map: dict[str, str] = {k: (v.label or k) for k, v in all_schemas.items()}

    async def _count_one(kind: str) -> dict[str, Any]:
        async with semaphore:
            count = await client.count(kind=kind, branch=branch)
        done_counter[0] += 1
        if on_progress is not None:
            await on_progress(done_counter[0], total)
        return {"kind": kind, "label": label_map.get(kind, kind), "count": count}

    results = await asyncio.gather(*[_count_one(kind) for kind in kinds])
    return sorted(results, key=operator.itemgetter("count"), reverse=True)


_MAX_DISTINCT_FOR_CHART = 10


def compute_field_distributions(
    nodes: list[dict[str, Any]], attributes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Compute value distribution for chartable attributes.

    An attribute is chartable if its kind is "Dropdown" OR it has <= 10 distinct values.

    Args:
        nodes: List of node dicts (as returned by fetch_nodes_for_kind rows).
        attributes: List of attribute descriptor dicts with at least "name" and "kind" keys.

    Returns:
        List of dicts: {field: str, distribution: [{value: str, count: int}]}
        Only includes chartable attributes.
    """
    if not nodes:
        return []

    result: list[dict[str, Any]] = []
    for attr in attributes:
        field_name: str = attr["name"]
        attr_kind: str = attr.get("kind", "")
        values = [str(node.get(field_name, "")) for node in nodes]
        counter = Counter(values)
        distinct_count = len(counter)
        is_chartable = attr_kind == "Dropdown" or distinct_count <= _MAX_DISTINCT_FOR_CHART
        if not is_chartable:
            continue
        distribution = [{"value": value, "count": cnt} for value, cnt in counter.most_common()]
        result.append({"field": field_name, "distribution": distribution})
    return result


def compute_relationship_distributions(
    nodes: list[dict[str, Any]], relationships: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Compute distribution of relationship peers.

    For 'one' cardinality: count distinct peer values.
    For 'many' cardinality: flatten all peer lists, count distinct values.

    Args:
        nodes: List of node dicts (as returned by fetch_nodes_for_kind rows).
        relationships: List of relationship descriptor dicts with at least
            "name" and "cardinality" keys.

    Returns:
        List of dicts: {field: str, distribution: [{value: str, count: int}]}
    """
    if not nodes:
        return []

    result: list[dict[str, Any]] = []
    for rel in relationships:
        field_name: str = rel["name"]
        cardinality: str = rel.get("cardinality", "one")
        all_values: list[str] = []

        for node in nodes:
            raw = node.get(field_name)
            if raw is None:
                continue
            if cardinality == "many":
                if isinstance(raw, list):
                    all_values.extend(str(v) for v in raw)
                else:
                    all_values.append(str(raw))
            else:
                all_values.append(str(raw))

        if not all_values:
            continue

        counter = Counter(all_values)
        distribution = [{"value": value, "count": cnt} for value, cnt in counter.most_common()]
        result.append({"field": field_name, "distribution": distribution})

    return result
