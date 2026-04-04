"""Tests for server configuration loading."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from infrahub_mcp.config import ServerConfig, load_config


class TestServerConfig:
    def test_defaults(self) -> None:
        config = ServerConfig()
        assert config.read_only is False
        assert config.branch_pattern == "mcp/session-{date}-{hex}"
        assert config.max_branch_retries == 5

    def test_frozen(self) -> None:
        config = ServerConfig()
        with pytest.raises(AttributeError):
            config.read_only = True  # type: ignore[misc]


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

    def test_max_branch_retries_invalid_string(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_MAX_BRANCH_RETRIES": "abc"}, clear=True):
            with pytest.raises(ValueError, match="must be an integer"):
                load_config()

    def test_max_branch_retries_too_low(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_MAX_BRANCH_RETRIES": "0"}, clear=True):
            with pytest.raises(ValueError, match="must be between 1 and 20"):
                load_config()

    def test_max_branch_retries_too_high(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_MAX_BRANCH_RETRIES": "100"}, clear=True):
            with pytest.raises(ValueError, match="must be between 1 and 20"):
                load_config()
