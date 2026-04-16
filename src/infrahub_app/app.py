"""FastMCPApp instance and shared context helpers."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Annotated, Any

from fastmcp.apps import FastMCPApp
from pydantic import BeforeValidator

if TYPE_CHECKING:
    from fastmcp import Context
    from infrahub_sdk.client import InfrahubClient

    from infrahub_mcp.utils import AppContext


def _coerce_filters(v: Any) -> dict[str, Any] | None:
    """Accept a dict or a JSON string for filters.

    The FastMCP dev UI sends form values as strings, so we need to
    parse JSON strings like '{"name__value": "atl1"}' into dicts.
    """
    if v is None:
        return None
    if isinstance(v, dict):
        return v
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return None
        try:
            parsed = json.loads(v)
        except json.JSONDecodeError as exc:
            msg = f'filters must be a JSON object, e.g. {{"name__value": "atl1"}}. Got: {v!r}'
            raise ValueError(msg) from exc
        if not isinstance(parsed, dict):
            msg = f"filters must be a JSON object, not {type(parsed).__name__}"
            raise ValueError(msg)
        return parsed
    return v


Filters = Annotated[dict[str, Any] | None, BeforeValidator(_coerce_filters)]

app = FastMCPApp("Infrahub")


def get_app_ctx(ctx: Context) -> AppContext:
    """Extract the AppContext from the MCP request context."""
    return ctx.request_context.lifespan_context  # type: ignore[union-attr,return-value]


def get_client(ctx: Context) -> InfrahubClient:
    """Extract the Infrahub SDK client from the MCP request context."""
    return get_app_ctx(ctx).client
