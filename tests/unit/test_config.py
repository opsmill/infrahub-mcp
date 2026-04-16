"""Tests for server configuration loading."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from infrahub_mcp.config import ServerConfig, load_config

# ---------------------------------------------------------------------------
# ServerConfig dataclass
# ---------------------------------------------------------------------------


def test_defaults() -> None:
    config = ServerConfig()
    assert config.max_query_depth == 2


def test_frozen() -> None:
    config = ServerConfig()
    with pytest.raises(AttributeError):
        config.max_query_depth = 3  # type: ignore[misc]


def test_max_query_depth_default() -> None:
    config = ServerConfig()
    assert config.max_query_depth == 2


# ---------------------------------------------------------------------------
# load_config()
# ---------------------------------------------------------------------------


def test_defaults_no_env() -> None:
    with patch.dict(os.environ, {}, clear=True):
        config = load_config()
    assert config.max_query_depth == 2


def test_max_query_depth_custom() -> None:
    with patch.dict(os.environ, {"INFRAHUB_MCP_MAX_QUERY_DEPTH": "3"}, clear=True):
        config = load_config()
    assert config.max_query_depth == 3


def test_max_query_depth_zero() -> None:
    with patch.dict(os.environ, {"INFRAHUB_MCP_MAX_QUERY_DEPTH": "0"}, clear=True):
        config = load_config()
    assert config.max_query_depth == 0


def test_max_query_depth_negative() -> None:
    with patch.dict(os.environ, {"INFRAHUB_MCP_MAX_QUERY_DEPTH": "-1"}, clear=True):
        with pytest.raises(ValueError, match="must be between 0 and 5"):
            load_config()


def test_max_query_depth_too_high() -> None:
    with patch.dict(os.environ, {"INFRAHUB_MCP_MAX_QUERY_DEPTH": "10"}, clear=True):
        with pytest.raises(ValueError, match="must be between 0 and 5"):
            load_config()


def test_max_query_depth_invalid_string() -> None:
    with patch.dict(os.environ, {"INFRAHUB_MCP_MAX_QUERY_DEPTH": "abc"}, clear=True):
        with pytest.raises(ValueError, match="must be an integer"):
            load_config()
