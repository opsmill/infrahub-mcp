"""Schema discovery tool for the Infrahub MCP server."""

import json
from typing import TYPE_CHECKING, Annotated

import toon
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from infrahub_sdk.exceptions import SchemaNotFoundError
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.schema import get_schema_catalog, get_schema_detail, get_valid_kinds_summary
from infrahub_mcp.utils import _log_and_raise_error, get_client, get_config

if TYPE_CHECKING:
    from infrahub_sdk.client import InfrahubClient

mcp: FastMCP = FastMCP(name="Infrahub Schema")


@mcp.tool(tags={"schema", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def get_schema(
    ctx: Context,
    kind: Annotated[
        str | None,
        Field(
            default=None,
            description="Kind to get detail for. Omit to list all available kinds.",
        ),
    ] = None,
    branch: Annotated[
        str | None,
        Field(default=None, description="Branch to query. Defaults to the default branch."),
    ] = None,
    depth: Annotated[
        int | None,
        Field(
            default=None,
            description=(
                "Relationship traversal depth for schema expansion. "
                "When set, each relationship includes the full schema of its peer kind, "
                "nested up to this many levels. 0 = no expansion (default when omitted). "
                "Capped at the server's INFRAHUB_MCP_MAX_QUERY_DEPTH setting."
            ),
        ),
    ] = None,
) -> str:
    """Discover available schema kinds and their structure in Infrahub.

    Call without arguments to list all available kinds.
    Call with a ``kind`` to see its attributes, relationships, and valid filter keys.
    Set ``depth`` to include related kinds' schemas nested inline.

    Prefer reading the ``infrahub://schema`` resource if your client supports
    MCP resources — this tool provides the same data for clients that don't.

    Args:
        kind: Optional kind to get detail for. Omit to list all kinds.
        branch: Branch to query. Defaults to the default branch.
        depth: Relationship depth (0 = no expansion). Capped at server max.

    Returns:
        JSON catalog (no kind) or TOON-encoded schema detail (with kind).
    """
    client: InfrahubClient = get_client(ctx)  # type: ignore[assignment]

    if kind is None:
        catalog = await get_schema_catalog(client, branch=branch)
        return json.dumps(catalog, separators=(",", ":"))

    resolved_depth = 0
    if depth is not None:
        if depth < 0:
            msg = "depth must be non-negative."
            raise ToolError(msg)
        config = get_config(ctx)
        resolved_depth = min(depth, config.max_query_depth)

    try:
        detail = await get_schema_detail(client, kind=kind, branch=branch, depth=resolved_depth)
    except SchemaNotFoundError:
        valid = await get_valid_kinds_summary(client, branch=branch)
        await _log_and_raise_error(
            ctx=ctx,
            error=f"Schema not found for kind: {kind}.",
            remediation=f"{valid}\nCall get_schema() for the full catalog, or get_schema(kind='<kind>') for details.",
        )

    return toon.encode(detail)
