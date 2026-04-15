"""FastMCPApp instance and shared context helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastmcp.apps import FastMCPApp

if TYPE_CHECKING:
    from fastmcp import Context
    from infrahub_sdk.client import InfrahubClient

    from infrahub_mcp.utils import AppContext

app = FastMCPApp("Infrahub")


def get_app_ctx(ctx: Context) -> AppContext:
    """Extract the AppContext from the MCP request context."""
    return ctx.request_context.lifespan_context  # type: ignore[union-attr,return-value]


def get_client(ctx: Context) -> InfrahubClient:
    """Extract the Infrahub SDK client from the MCP request context."""
    return get_app_ctx(ctx).client
