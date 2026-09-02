"""Tests for server startup env validation (``_validate_env``)."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

import pytest

from infrahub_mcp.config import ServerConfig
from infrahub_mcp.server import _validate_env, app_lifespan, mcp


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

    def test_token_combined_with_username_password_raises(self) -> None:
        # The SDK Config rejects this combination; catch it here so a credential mix
        # spread across .mcp.json, .env and the real environment gets actionable guidance
        # instead of a raw pydantic ValidationError from InfrahubClient().
        env = {
            "INFRAHUB_ADDRESS": "http://infrahub",
            "INFRAHUB_API_TOKEN": "secret",
            "INFRAHUB_USERNAME": "alice",
            "INFRAHUB_PASSWORD": "hunter2",
        }
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError, match="Conflicting credentials"):
                _validate_env()

    def test_lowercase_credentials_accepted(self) -> None:
        # The SDK settings model is case-insensitive, so lowercase spellings do reach
        # InfrahubClient() and must not be reported as missing here.
        env = {"infrahub_address": "http://infrahub", "infrahub_api_token": "secret"}
        with patch.dict(os.environ, env, clear=True):
            _validate_env()

    def test_lowercase_password_conflicts_with_token(self) -> None:
        # Same case-insensitivity, seen from the other side: a lowercase password still
        # reaches the SDK, so the conflict must surface here rather than as a raw
        # pydantic ValidationError from InfrahubClient().
        env = {
            "INFRAHUB_ADDRESS": "http://infrahub",
            "INFRAHUB_API_TOKEN": "secret",
            "infrahub_username": "alice",
            "infrahub_password": "hunter2",
        }
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError, match="Conflicting credentials"):
                _validate_env()

    def test_token_combined_with_username_only_raises(self) -> None:
        env = {
            "INFRAHUB_ADDRESS": "http://infrahub",
            "INFRAHUB_API_TOKEN": "secret",
            "INFRAHUB_USERNAME": "alice",
        }
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(RuntimeError, match="must be set together"):
                _validate_env()


class TestLifespanEnvPriming:
    async def test_dotenv_credentials_satisfy_validation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """A .env supplying both connection variables must get the server started.

        Covers the wiring — priming has to run inside ``app_lifespan`` *before*
        ``_validate_env()``, which is the whole point of the feature.
        """
        (tmp_path / ".env").write_text("INFRAHUB_ADDRESS=http://infrahub\nINFRAHUB_API_TOKEN=from-dotenv\n")
        monkeypatch.chdir(tmp_path)
        with patch.dict(os.environ, {}, clear=True):
            async with app_lifespan(mcp) as context:
                assert os.environ["INFRAHUB_ADDRESS"] == "http://infrahub"
                assert context.client is not None
