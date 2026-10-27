"""Tests for server startup env validation (``_validate_env``)."""

from __future__ import annotations

import os
import shutil
import subprocess  # noqa: S404 - native Git only creates isolated test repositories
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

    async def test_commented_token_placeholder_fails_startup(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unfilled ``INFRAHUB_API_TOKEN= # ...`` line must stop startup, not be sent as a token."""
        (tmp_path / ".env").write_text("INFRAHUB_ADDRESS=http://infrahub\nINFRAHUB_API_TOKEN= # fill me in\n")
        monkeypatch.chdir(tmp_path)
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(RuntimeError, match="Authentication required"):
                async with app_lifespan(mcp):
                    pass

    async def test_commented_token_placeholder_allows_password_login(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A blank token placeholder next to a username and password must not count as a token."""
        (tmp_path / ".env").write_text(
            "INFRAHUB_ADDRESS=http://infrahub\n"
            "INFRAHUB_API_TOKEN= # fill me in\n"
            "INFRAHUB_USERNAME=alice\n"
            "INFRAHUB_PASSWORD=hunter2\n"
        )
        monkeypatch.chdir(tmp_path)
        with patch.dict(os.environ, {}, clear=True):
            async with app_lifespan(mcp) as context:
                assert context.client is not None
                assert context.client.config.password_authentication
                assert "X-INFRAHUB-KEY" not in context.client.headers


def _git(directory: Path, *args: str) -> None:
    """Create test fixtures with native Git, independent of the SDK's Dulwich reader."""
    executable = shutil.which("git")
    assert executable is not None
    subprocess.run(  # noqa: S603 - fixed executable and test-controlled arguments
        [executable, "-C", str(directory), *args],
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull},
    )


class TestLifespanGitBranch:
    @pytest.mark.parametrize("linked_worktree", [False, True], ids=["repository", "linked-worktree"])
    async def test_git_branch_reaches_real_sdk_client(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, linked_worktree: bool
    ) -> None:
        """The SDK's Git branch lookup must work when launched from either checkout layout."""
        _git(tmp_path, "init", "--initial-branch=sdk-branch")
        checkout = tmp_path
        expected_branch = "sdk-branch"
        if linked_worktree:
            _git(
                tmp_path,
                "-c",
                "user.name=Test",
                "-c",
                "user.email=test@example.invalid",
                "-c",
                f"core.hooksPath={os.devnull}",
                "commit",
                "--allow-empty",
                "--no-gpg-sign",
                "-m",
                "Test fixture",
            )
            checkout = tmp_path / "linked"
            expected_branch = "sdk-worktree"
            _git(tmp_path, "worktree", "add", "-b", expected_branch, str(checkout))
        monkeypatch.chdir(checkout)
        env = {
            "INFRAHUB_MCP_ENV_FILE": "",
            "INFRAHUB_ADDRESS": "http://infrahub",
            "INFRAHUB_API_TOKEN": "test-token",
            "INFRAHUB_DEFAULT_BRANCH": "fallback",
            "INFRAHUB_DEFAULT_BRANCH_FROM_GIT": "true",
        }

        with patch.dict(os.environ, env, clear=True):
            async with app_lifespan(mcp) as context:
                assert context.client is not None
                assert context.client.default_branch == expected_branch

    async def test_explicit_branch_does_not_require_or_create_git_repository(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        env = {
            "INFRAHUB_MCP_ENV_FILE": "",
            "INFRAHUB_ADDRESS": "http://infrahub",
            "INFRAHUB_API_TOKEN": "test-token",
            "INFRAHUB_DEFAULT_BRANCH": "configured-branch",
            "INFRAHUB_DEFAULT_BRANCH_FROM_GIT": "false",
        }

        with patch.dict(os.environ, env, clear=True):
            async with app_lifespan(mcp) as context:
                assert context.client is not None
                assert context.client.default_branch == "configured-branch"

        assert not (tmp_path / ".git").exists()
