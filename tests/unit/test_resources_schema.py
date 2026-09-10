"""Tests for the schema resources (``resources/schema.py``) read through an in-memory client.

The handlers' upstream helpers are patched to raise, so neither a lifespan
context nor a live Infrahub instance is needed: what is under test is how a
failure inside a resource handler reaches the MCP client. FastMCP re-raises a
``FastMCPError`` (``ToolError``, ``ResourceError``) from a resource handler
with its message intact, but wraps any other exception in a generic
``ResourceError("Error reading resource '<uri>': ...")`` before the middleware
chain sees it.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError
from infrahub_sdk.exceptions import BranchNotFoundError
from mcp import McpError

from infrahub_mcp.resources import schema as schema_resources

SDL_URI = "infrahub://graphql-schema"
CATALOG_URI = "infrahub://schema"


async def _read_error(uri: str) -> str:
    """Read *uri* through the in-memory client and return the error message the client receives."""
    async with Client(schema_resources.mcp) as client:
        with pytest.raises(McpError) as excinfo:
            await client.read_resource(uri)
    return str(excinfo.value)


async def test_graphql_schema_wraps_gone_branch_like_schema_catalog() -> None:
    """A gone branch surfaces as the siblings' ``Branch not found`` message, not FastMCP's generic wrapper."""
    with patch.object(
        schema_resources, "get_cached_graphql_sdl", AsyncMock(side_effect=BranchNotFoundError(identifier="gone"))
    ):
        sdl_message = await _read_error(SDL_URI)
    with patch.object(
        schema_resources, "get_schema_catalog", AsyncMock(side_effect=BranchNotFoundError(identifier="gone"))
    ):
        catalog_message = await _read_error(CATALOG_URI)

    assert sdl_message.startswith("Branch not found: ")
    assert "'gone'" in sdl_message
    assert "Error reading resource" not in sdl_message
    assert sdl_message == catalog_message


async def test_graphql_schema_passes_tool_error_message_through() -> None:
    """``ToolError`` is a ``FastMCPError``: FastMCP re-raises it unchanged, so its message reaches the client intact."""
    message = "Schema temporarily unavailable for branch 'main': probe timed out"
    with patch.object(schema_resources, "get_cached_graphql_sdl", AsyncMock(side_effect=ToolError(message))):
        assert await _read_error(SDL_URI) == message
