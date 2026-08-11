"""Tests for marketplace config gating and tool registration metadata."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from fastmcp import Client
from pydantic import ValidationError

from infrahub_mcp.config import ServerConfig
from infrahub_mcp.tools.marketplace import install_mcp, mcp


class TestMarketplaceConfig:
    def test_defaults_enabled(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = ServerConfig()
        assert config.marketplace_enabled is True
        assert config.marketplace_url == "https://marketplace.infrahub.app"

    def test_url_trailing_slash_stripped(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_MARKETPLACE_URL": "https://mp.example.com/"}, clear=True):
            config = ServerConfig()
        assert config.marketplace_url == "https://mp.example.com"

    def test_can_disable(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_MARKETPLACE_ENABLED": "false"}, clear=True):
            config = ServerConfig()
        assert config.marketplace_enabled is False

    @pytest.mark.parametrize("bad_url", ["not-a-url", "ftp://mp.example.com", "marketplace.infrahub.app"])
    def test_invalid_url_rejected_at_startup(self, bad_url: str) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_MARKETPLACE_URL": bad_url}, clear=True):
            with pytest.raises(ValidationError, match="valid http"):
                ServerConfig()


class TestMarketplaceToolMetadata:
    """The read/write tags and readOnlyHint are what the middleware and read-only gate key on."""

    @pytest.mark.parametrize("name", ["marketplace_search", "marketplace_get_schema", "marketplace_get_collection"])
    async def test_read_tools_are_read_only(self, name: str) -> None:
        tool = await mcp.get_tool(name)
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert "retrieve" in tool.tags
        assert "write" not in tool.tags

    async def test_install_is_write_tagged(self) -> None:
        # The "write" tag is what ReadOnlyMiddleware blocks and AuthMiddleware scopes (FR-005/FR-006).
        tool = await install_mcp.get_tool("marketplace_install")
        assert "write" in tool.tags
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is False

    async def test_install_not_on_read_subapp(self) -> None:
        # Install must live on install_mcp (mounted only when not read-only), never on the read sub-app.
        async with Client(mcp) as client:
            names = {tool.name for tool in await client.list_tools()}
        assert names == {"marketplace_search", "marketplace_get_schema", "marketplace_get_collection"}
        assert "marketplace_install" not in names
