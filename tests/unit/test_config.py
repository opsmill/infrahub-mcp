"""Tests for server configuration loading."""

from __future__ import annotations

import os
from unittest.mock import patch

from infrahub_mcp.config import ServerConfig, load_config


class TestServerConfig:
    def test_defaults(self) -> None:
        config = ServerConfig()
        assert config.read_only is False
        assert config.branch_pattern == "mcp/session-{date}-{hex}"
        assert config.max_branch_retries == 5

    def test_frozen(self) -> None:
        config = ServerConfig()
        try:
            config.read_only = True  # type: ignore[misc]
            raise AssertionError("Expected FrozenInstanceError")  # noqa: TRY301
        except AttributeError:
            pass


class TestLoadConfig:
    def test_defaults_no_env(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = load_config()
        assert config.read_only is False
        assert config.branch_pattern == "mcp/session-{date}-{hex}"
        assert config.max_branch_retries == 5

    def test_read_only_true(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_READ_ONLY": "true"}, clear=True):
            config = load_config()
        assert config.read_only is True

    def test_read_only_yes(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_READ_ONLY": "YES"}, clear=True):
            config = load_config()
        assert config.read_only is True

    def test_read_only_one(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_READ_ONLY": "1"}, clear=True):
            config = load_config()
        assert config.read_only is True

    def test_read_only_false(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_READ_ONLY": "false"}, clear=True):
            config = load_config()
        assert config.read_only is False

    def test_branch_pattern_custom(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_BRANCH_PATTERN": "mcp/{user}-{date}"}, clear=True):
            config = load_config()
        assert config.branch_pattern == "mcp/{user}-{date}"

    def test_branch_pattern_fixed(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_BRANCH_PATTERN": "staging"}, clear=True):
            config = load_config()
        assert config.branch_pattern == "staging"

    def test_max_branch_retries_custom(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_MAX_BRANCH_RETRIES": "10"}, clear=True):
            config = load_config()
        assert config.max_branch_retries == 10
