"""Tests for marketplace config gating and tool registration metadata."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest
from fastmcp import Client
from pydantic import ValidationError

from infrahub_mcp.config import ServerConfig
from infrahub_mcp.tools.marketplace import install_mcp, mcp

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


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
        assert tool is not None
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is True
        assert "retrieve" in tool.tags
        assert "write" not in tool.tags

    async def test_install_is_write_tagged(self) -> None:
        # The "write" tag is what ReadOnlyMiddleware blocks and AuthMiddleware scopes (FR-005/FR-006).
        tool = await install_mcp.get_tool("marketplace_install")
        assert tool is not None
        assert "write" in tool.tags
        assert tool.annotations is not None
        assert tool.annotations.readOnlyHint is False

    async def test_install_not_on_read_subapp(self) -> None:
        # Install must live on install_mcp (mounted only when not read-only), never on the read sub-app.
        async with Client(mcp) as client:
            names = {tool.name for tool in await client.list_tools()}
        assert names == {"marketplace_search", "marketplace_get_schema", "marketplace_get_collection"}
        assert "marketplace_install" not in names


class TestInstallErrorPaths:
    """``marketplace_install`` must route every failure through the sanitised MCP error path.

    Both of these previously escaped as raw exceptions: the ref preflight raised
    ``MarketplaceError`` outside the ``try``, and a malformed payload raised ``yaml.YAMLError``.
    """

    async def test_invalid_ref_is_a_tool_error_not_a_raw_exception(self) -> None:
        async with Client(install_mcp) as client:
            result = await client.call_tool("marketplace_install", {"ref": "not-a-valid-ref"}, raise_on_error=False)
        assert result.is_error
        assert "namespace/name" in str(result.content)

    async def test_malformed_yaml_is_a_tool_error_not_a_raw_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from infrahub_mcp.marketplace import SchemaPayload  # noqa: PLC0415
        from infrahub_mcp.tools import marketplace as mp_tools  # noqa: PLC0415

        class _StubClient:
            async def get_schema(self, ref: str, version: str | None = None) -> SchemaPayload:
                # Unbalanced flow sequence — yaml.safe_load_all raises while iterating.
                return SchemaPayload(
                    namespace="opsmill", name="broken", resolved_version="1.0.0", yaml="nodes: [unclosed", metadata=None
                )

        # Stub the client factory, not the class: the tool builds its client from the
        # lifespan AppContext, which a bare in-process Client does not provide.
        @asynccontextmanager
        async def _stub_factory(ctx: object) -> AsyncIterator[_StubClient]:
            yield _StubClient()

        monkeypatch.setattr(mp_tools, "_marketplace_client", _stub_factory)
        async with Client(install_mcp) as client:
            result = await client.call_tool("marketplace_install", {"ref": "opsmill/broken"}, raise_on_error=False)
        assert result.is_error
        assert "not valid YAML" in str(result.content)
