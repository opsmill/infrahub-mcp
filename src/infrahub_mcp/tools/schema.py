"""Schema discovery tool for the Infrahub MCP server."""

import json
from typing import TYPE_CHECKING, Annotated

import toon
from fastmcp import Context, FastMCP
from infrahub_sdk.exceptions import SchemaNotFoundError
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.schema import get_schema_catalog, get_schema_detail, get_valid_kinds_summary
from infrahub_mcp.utils import _log_and_raise_error, get_client

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
            description=("Kind to get detail for. Omit to list all available kinds."),
        ),
    ] = None,
    branch: Annotated[
        str | None,
        Field(default=None, description="Branch to query. Defaults to the default branch."),
    ] = None,
) -> str:
    """Discover available schema kinds and their structure in Infrahub.

    Call without arguments to list all available kinds.
    Call with a ``kind`` to see its attributes, relationships, and valid filter keys.

    Prefer reading the ``infrahub://schema`` resource if your client supports
    MCP resources — this tool provides the same data for clients that don't.

    Args:
        kind: Optional kind to get detail for. Omit to list all kinds.
        branch: Branch to query. Defaults to the default branch.

    Returns:
        JSON catalog (no kind) or TOON-encoded schema detail (with kind).
    """
    client: InfrahubClient = get_client(ctx)  # type: ignore[assignment]

    if kind is None:
        catalog = await get_schema_catalog(client, branch=branch)
        return json.dumps(catalog, separators=(",", ":"))

    try:
        detail = await get_schema_detail(client, kind=kind, branch=branch)
    except SchemaNotFoundError:
        valid = await get_valid_kinds_summary(client, branch=branch)
        await _log_and_raise_error(
            ctx=ctx,
            error=f"Schema not found for kind: {kind}.",
            remediation=f"{valid}\nCall get_schema() for the full catalog, or get_schema(kind='<kind>') for details.",
        )

    return toon.encode(detail)
