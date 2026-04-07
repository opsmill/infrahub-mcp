"""Tests for auth provider factory and user identity extraction."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from infrahub_mcp.auth import create_auth_provider, get_user_from_token, sanitize_user_for_branch
from infrahub_mcp.config import ServerConfig


class TestCreateAuthProvider:
    def test_mode_none_returns_none(self) -> None:
        config = ServerConfig(auth_mode="none")
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


class TestSanitizeUserForBranch:
    def test_email_address(self) -> None:
        assert sanitize_user_for_branch("alice@example.com") == "alice-example.com"

    def test_plain_username(self) -> None:
        assert sanitize_user_for_branch("alice") == "alice"

    def test_spaces_and_special_chars(self) -> None:
        assert sanitize_user_for_branch("Alice B. Carol!") == "Alice-B.-Carol"

    def test_empty_string(self) -> None:
        assert sanitize_user_for_branch("") == "anonymous"

    def test_only_special_chars(self) -> None:
        assert sanitize_user_for_branch("@@@") == "anonymous"

    def test_slashes_preserved(self) -> None:
        assert sanitize_user_for_branch("org/team/alice") == "org/team/alice"

    def test_consecutive_hyphens_collapsed(self) -> None:
        assert sanitize_user_for_branch("a@@b") == "a-b"


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
