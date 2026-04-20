"""Tests for auth provider factory and user identity extraction."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

from infrahub_mcp.auth import (
    _passthrough_token,
    assert_writable_branch,
    create_auth_provider,
    get_passthrough_token,
    get_user_from_token,
    reset_passthrough_token,
    sanitize_user_for_branch,
    set_passthrough_token,
)
from infrahub_mcp.config import ServerConfig


class TestCreateAuthProvider:
    def test_mode_none_returns_none(self) -> None:
        config = ServerConfig(auth_mode="none")
        result = create_auth_provider(config)
        assert result is None

    def test_mode_token_passthrough_returns_none(self) -> None:
        config = ServerConfig(auth_mode="token-passthrough")
        result = create_auth_provider(config)
        assert result is None

    def test_mode_oidc_returns_oidc_proxy(self) -> None:
        config = ServerConfig(
            auth_mode="oidc",
            oidc_config_url="https://accounts.google.com/.well-known/openid-configuration",
            oidc_client_id="my-client",
            oidc_base_url="https://mcp.example.com",
        )
        mock_proxy = MagicMock()
        with patch("fastmcp.server.auth.OIDCProxy", return_value=mock_proxy) as mock_cls:
            result = create_auth_provider(config)
        assert result is mock_proxy
        mock_cls.assert_called_once_with(
            config_url="https://accounts.google.com/.well-known/openid-configuration",
            client_id="my-client",
            base_url="https://mcp.example.com",
        )

    def test_mode_oidc_with_optional_fields(self) -> None:
        config = ServerConfig(
            auth_mode="oidc",
            oidc_config_url="https://example.com/.well-known/openid-configuration",
            oidc_client_id="my-client",
            oidc_client_secret="my-secret",
            oidc_base_url="https://mcp.example.com",
            oidc_audience="my-api",
        )
        mock_proxy = MagicMock()
        with patch("fastmcp.server.auth.OIDCProxy", return_value=mock_proxy) as mock_cls:
            result = create_auth_provider(config)
        assert result is mock_proxy
        mock_cls.assert_called_once_with(
            config_url="https://example.com/.well-known/openid-configuration",
            client_id="my-client",
            client_secret="my-secret",
            base_url="https://mcp.example.com",
            audience="my-api",
        )


class TestPassthroughTokenContextVar:
    @pytest.fixture(autouse=True)
    def _clean_passthrough_token(self) -> Generator[None]:
        token = _passthrough_token.set(None)
        yield
        _passthrough_token.reset(token)

    def test_default_is_none(self) -> None:
        assert get_passthrough_token() is None

    def test_set_and_get(self) -> None:
        set_passthrough_token("my-token")
        assert get_passthrough_token() == "my-token"

    def test_overwrite(self) -> None:
        set_passthrough_token("first")
        set_passthrough_token("second")
        assert get_passthrough_token() == "second"

    def test_reset_restores_previous_value(self) -> None:
        token = set_passthrough_token("temporary")
        assert get_passthrough_token() == "temporary"
        reset_passthrough_token(token)
        assert get_passthrough_token() is None


class TestSanitizeUserForBranch:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("alice@example.com", "alice-example.com"),
            ("alice", "alice"),
            ("Alice B. Carol!", "Alice-B.-Carol"),
            ("", "anonymous"),
            ("@@@", "anonymous"),
            ("org/team/alice", "org/team/alice"),
            ("a@@b", "a-b"),
            ("a..b", "a.b"),
            ("../alice", "alice"),
            ("team//alice", "team/alice"),
            ("team/.alice", "team/alice"),
            ("alice.lock", "alice"),
            (".alice", "alice"),
            ("alice/", "alice"),
            ("../team//alice.lock", "team/alice"),
        ],
    )
    def test_sanitize(self, raw: str, expected: str) -> None:
        assert sanitize_user_for_branch(raw) == expected


class TestGetUserFromToken:
    def test_no_token_returns_anonymous(self) -> None:
        with patch("fastmcp.server.middleware.authorization.get_access_token", return_value=None):
            assert get_user_from_token() == "anonymous"

    def test_token_with_email(self) -> None:
        token = MagicMock()
        token.claims = {"email": "alice@example.com", "sub": "user-123"}
        with patch("fastmcp.server.middleware.authorization.get_access_token", return_value=token):
            assert get_user_from_token(claim="email") == "alice-example.com"

    def test_token_falls_back_to_sub(self) -> None:
        token = MagicMock()
        token.claims = {"sub": "user-123"}
        with patch("fastmcp.server.middleware.authorization.get_access_token", return_value=token):
            assert get_user_from_token(claim="email") == "user-123"

    def test_token_with_preferred_username(self) -> None:
        token = MagicMock()
        token.claims = {"preferred_username": "alice", "sub": "user-123"}
        with patch("fastmcp.server.middleware.authorization.get_access_token", return_value=token):
            assert get_user_from_token(claim="preferred_username") == "alice"

    def test_import_error_returns_anonymous(self) -> None:
        with patch("fastmcp.server.middleware.authorization.get_access_token", side_effect=ImportError):
            assert get_user_from_token() == "anonymous"

    def test_empty_claims_returns_anonymous(self) -> None:
        token = MagicMock()
        token.claims = {}
        with patch("fastmcp.server.middleware.authorization.get_access_token", return_value=token):
            assert get_user_from_token() == "anonymous"


class TestAssertWritableBranch:
    def test_rejects_protected_branch(self) -> None:
        with pytest.raises(ValueError, match="protected branch 'main'"):
            assert_writable_branch("main", protected=["main"])

    def test_allows_unprotected_branch(self) -> None:
        assert_writable_branch("mcp/session-20260420-abcd", protected=["main"])
        assert_writable_branch("feature/x", protected=["main"])

    def test_empty_protected_list_allows_any(self) -> None:
        assert_writable_branch("main", protected=[])

    def test_custom_protected_list(self) -> None:
        with pytest.raises(ValueError, match="protected branch 'release'"):
            assert_writable_branch("release", protected=["main", "release"])
        assert_writable_branch("main", protected=["release"])
