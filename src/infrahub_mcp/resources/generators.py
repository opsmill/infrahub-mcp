"""Generator resources for the Infrahub MCP server."""

import json
from typing import TYPE_CHECKING, Any

import toon
from fastmcp import Context, FastMCP
from infrahub_sdk.exceptions import GraphQLError

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient

mcp: FastMCP = FastMCP(name="Infrahub Generator Resources")


@mcp.resource(
    "infrahub://generators",
    name="Generator Definitions",
    description=(
        "All generator definitions available in this Infrahub instance, "
        "encoded in TOON tabular format. Each entry includes the generator's "
        "id, name, description, query, class_name, parameters, and target group. "
        "Use this to discover which generators exist before calling run_generator."
    ),
    mime_type="text/plain",
)
async def generator_catalog(ctx: Context) -> str:
    """Return all generator definitions as a TOON-encoded list."""
    client: InfrahubClient = ctx.request_context.lifespan_context.client  # type: ignore[union-attr]

    try:
        generators = await client.all(kind="CoreGeneratorDefinition", include=["targets"], prefetch_relationships=True)
    except GraphQLError as exc:
        return json.dumps({"error": str(exc)}, separators=(",", ":"))

    results: list[dict[str, Any]] = []
    for gen in generators:
        results.append(
            {
                "id": gen.id,
                "display_label": gen.display_label,
                "description": gen.description.value,  # type: ignore[union-attr]
                "targets_group_id": gen.targets.peer.id if gen.targets else None,
                "targets_group": gen.targets.peer.display_label if gen.targets else None,
            }
        )

    if not results:
        return "No generator definitions found."
    return toon.encode(results)
