"""Tests for server startup env validation (``_validate_env``)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from collections.abc import Generator

import pytest

from infrahub_mcp.config import ServerConfig
from infrahub_mcp.server import _validate_env


@pytest.fixture(autouse=True)
def _force_none_auth_mode() -> Generator[None]:
    """Ensure _validate_env tests run with auth_mode='none' regardless of env."""
    with patch("infrahub_mcp.server._config", ServerConfig(auth_mode="none")):
        yield


class TestValidateEnv:
    def test_api_token_only(self) -> None:
        env = {"INFRAHUB_ADDRESS": "http://infrahub", "INFRAHUB_API_TOKEN": "secret"}
        with patch.dict(os.environ, env, clear=True):
            _validate_env()

    def test_username_password(self) -> None:
        env = {
            "INFRAHUB_ADDRESS": "http://infrahub",
            "INFRAHUB_USERNAME": "alice",
            "INFRAHUB_PASSWORD": "hunter2",
        }
        with patch.dict(os.environ, env, clear=True):
            _validate_env()

    def test_missing_address_raises(self) -> None:
        env = {"INFRAHUB_API_TOKEN": "secret"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError, match="INFRAHUB_ADDRESS is required"):
                _validate_env()

    def test_missing_credentials_raises(self) -> None:
        env = {"INFRAHUB_ADDRESS": "http://infrahub"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError, match="Authentication required"):
                _validate_env()

    def test_username_without_password_raises(self) -> None:
        env = {"INFRAHUB_ADDRESS": "http://infrahub", "INFRAHUB_USERNAME": "alice"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError, match="Authentication required"):
                _validate_env()

    def test_password_without_username_raises(self) -> None:
        env = {"INFRAHUB_ADDRESS": "http://infrahub", "INFRAHUB_PASSWORD": "hunter2"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError, match="Authentication required"):
                _validate_env()
