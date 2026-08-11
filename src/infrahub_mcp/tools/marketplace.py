"""Marketplace discovery and install tools for the Infrahub MCP server.

Read tools (search / get_schema / get_collection) live on ``mcp`` and are anonymous,
read-only, and gated by ``marketplace_enabled``. The ``"write"``-tagged
``marketplace_install`` lives on ``install_mcp`` and is mounted only when the server
is not read-only — it loads a schema onto the session branch via the SDK for human
review (branch-safe by default).
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Annotated, Any

import yaml
from fastmcp import Context, FastMCP
from infrahub_sdk import Config
from infrahub_sdk.exceptions import Error as SdkError
from mcp.types import ToolAnnotations
from pydantic import Field

from infrahub_mcp.marketplace import (
    MarketplaceClient,
    MarketplaceError,
    make_marketplace_http_client,
    parse_identifier,
)
from infrahub_mcp.utils import (
    AppContext,
    _log_and_raise_error,
    get_client,
    get_or_create_session_branch,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from infrahub_sdk.config import ConfigBase

mcp: FastMCP = FastMCP(name="Infrahub Marketplace")
install_mcp: FastMCP = FastMCP(name="Infrahub Marketplace Install")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def _marketplace_client(ctx: Context) -> AsyncIterator[MarketplaceClient]:
    """Yield a :class:`MarketplaceClient` built from the server + SDK config.

    Uses the shared client's SDK config for proxy/TLS when available; otherwise falls
    back to a fresh SDK ``Config`` (env-driven). Carries no Infrahub credentials (FR-009).
    """
    if ctx.request_context is None:
        msg = "request_context must not be None"
        raise RuntimeError(msg)
    app_ctx: AppContext = ctx.request_context.lifespan_context
    sdk_config: ConfigBase | None = app_ctx.client.config if app_ctx.client is not None else Config()
    http_client = make_marketplace_http_client(sdk_config)
    try:
        yield MarketplaceClient(base_url=app_ctx.config.marketplace_url, http_client=http_client)
    finally:
        await http_client.aclose()


async def _fail(ctx: Context, exc: MarketplaceError) -> Any:
    """Surface a MarketplaceError as a sanitised MCP error (FR-010)."""
    await _log_and_raise_error(ctx=ctx, error=exc.message, remediation=exc.remediation)


@mcp.tool(tags={"marketplace", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def marketplace_search(  # noqa: PLR0913, PLR0917  # pylint: disable=too-many-arguments,too-many-positional-arguments
    ctx: Context,
    query: Annotated[str, Field(description="Free-text search term, e.g. 'dcim'.")],
    tag: Annotated[str | None, Field(default=None, description="Optional tag to filter by.")] = None,
    namespace: Annotated[str | None, Field(default=None, description="Optional namespace to filter by.")] = None,
    limit: Annotated[
        int | None, Field(default=None, description="Cap results to a single page; omit to fetch all.")
    ] = None,
    collections: Annotated[bool, Field(default=False, description="Search collections instead of schemas.")] = False,
) -> str:
    """Search the Infrahub Marketplace catalog for published schemas (or collections).

    Returns a ranked JSON list of catalog entries (namespace, name, version, tags,
    downloads). Empty list when nothing matches. Read-only and anonymous.

    Args:
        query: Free-text search term.
        tag: Optional tag filter.
        namespace: Optional namespace filter.
        limit: Cap results to a single page; omit to fetch all pages.
        collections: Search collections instead of schemas.

    Returns:
        Compact JSON array of catalog entries.
    """
    async with _marketplace_client(ctx) as client:
        try:
            entries = await client.search(query, tag=tag, namespace=namespace, limit=limit, collections=collections)
        except MarketplaceError as exc:
            await _fail(ctx, exc)
        return json.dumps([entry.model_dump(exclude_none=True) for entry in entries], separators=(",", ":"))


@mcp.tool(tags={"marketplace", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def marketplace_get_schema(
    ctx: Context,
    ref: Annotated[str, Field(description="Schema reference as 'namespace/name', e.g. 'opsmill/dcim'.")],
    version: Annotated[
        str | None, Field(default=None, description="Pinned version (e.g. '1.2.0'); omit for latest.")
    ] = None,
) -> str:
    """Retrieve a marketplace schema's catalog metadata and its YAML payload.

    Resolves ``namespace/name`` (schema wins if the name is also a collection) and
    returns the schema's metadata plus its decompressed YAML — the artifact you would
    review before installing. Read-only and anonymous.

    Args:
        ref: Schema reference 'namespace/name'.
        version: Optional pinned version; omit for the latest published version.

    Returns:
        JSON object with namespace, name, resolved_version, yaml, and metadata.
    """
    async with _marketplace_client(ctx) as client:
        try:
            payload = await client.get_schema(ref, version)
        except MarketplaceError as exc:
            await _fail(ctx, exc)
        return payload.model_dump_json(exclude_none=True)


@mcp.tool(tags={"marketplace", "retrieve"}, annotations=ToolAnnotations(readOnlyHint=True))
async def marketplace_get_collection(
    ctx: Context,
    ref: Annotated[str, Field(description="Collection reference as 'namespace/name', e.g. 'opsmill/starter'.")],
) -> str:
    """Retrieve a marketplace collection's metadata and its assembled member schemas.

    Returns the collection's ordered member schemas as a single valid multi-document
    YAML stream, so a themed bundle can be reviewed or adopted in one step. Read-only.

    Args:
        ref: Collection reference 'namespace/name'.

    Returns:
        JSON object with namespace, name, members, yaml (multi-doc), and metadata.
    """
    async with _marketplace_client(ctx) as client:
        try:
            payload = await client.get_collection(ref)
        except MarketplaceError as exc:
            await _fail(ctx, exc)
        return payload.model_dump_json(exclude_none=True)


@install_mcp.tool(tags={"marketplace", "write"}, annotations=ToolAnnotations(readOnlyHint=False))
async def marketplace_install(
    ctx: Context,
    ref: Annotated[str, Field(description="Schema reference as 'namespace/name' to install.")],
    version: Annotated[str | None, Field(default=None, description="Pinned version; omit for latest.")] = None,
) -> dict[str, Any]:
    """Install a marketplace schema into the connected Infrahub on the session branch.

    Downloads the schema YAML and loads it via the Infrahub SDK onto the auto-created
    session branch — the default branch is never modified. Review and merge via
    ``propose_changes``. Blocked in read-only mode. This action is audited.

    Args:
        ref: Schema reference 'namespace/name'.
        version: Optional pinned version; omit for the latest published version.

    Returns:
        Dict with the installed ref, resolved version, session branch, and a summary
        of what was applied.
    """
    # Validate the ref before any network work (fails fast on a bad ref).
    parse_identifier(ref)

    async with _marketplace_client(ctx) as client:
        try:
            payload = await client.get_schema(ref, version)
        except MarketplaceError as exc:
            await _fail(ctx, exc)

    schemas = [doc for doc in yaml.safe_load_all(payload.yaml) if isinstance(doc, dict)]
    if not schemas:
        await _log_and_raise_error(
            ctx=ctx,
            error=f"The downloaded schema {ref!r} contained no loadable YAML documents.",
            remediation="The marketplace payload may be malformed — inspect it with marketplace_get_schema.",
        )

    infrahub_client = get_client(ctx)
    session_branch = await get_or_create_session_branch(ctx)
    await ctx.info(f"Loading marketplace schema {ref} (v{payload.resolved_version}) onto branch {session_branch}")

    try:
        # Converge before returning: /api/schema/load answers before the new kinds have
        # propagated to every worker, so an agent that installs then immediately queries
        # the kind would race. Bounded by the SDK's schema_converge_timeout.
        response = await infrahub_client.schema.load(schemas=schemas, branch=session_branch, wait_until_converged=True)
    except SdkError as exc:
        await _log_and_raise_error(
            ctx=ctx,
            error=f"Failed to load schema {ref!r} onto branch {session_branch}: {exc}",
            remediation="The default branch is untouched. Fix the schema or branch and retry.",
        )

    if response.errors:
        await _log_and_raise_error(
            ctx=ctx,
            error=f"Schema {ref!r} failed Infrahub validation on branch {session_branch}: {response.errors}",
            remediation="The default branch is untouched. Adjust the schema and retry.",
        )

    return {
        "installed": ref,
        "resolved_version": payload.resolved_version,
        "branch": session_branch,
        "applied": {
            "schema_updated": response.schema_updated,
            "hash": response.hash,
            "previous_hash": response.previous_hash,
            "warnings": [str(warning) for warning in response.warnings],
        },
    }
