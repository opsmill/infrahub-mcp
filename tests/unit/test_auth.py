"""Tests for auth provider factory and user identity extraction."""

from __future__ import annotations

import string
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

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
            oidc_client_secret="my-secret",  # noqa: S106
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
            client_secret="my-secret",  # noqa: S106
            base_url="https://mcp.example.com",
            audience="my-api",
        )

    def test_mode_oidc_builds_real_proxy(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # The tests above replace OIDCProxy, so a renamed keyword or a broken import in
        # FastMCP's OAuth proxy (which pulls in authlib) would pass them. Build the real
        # class here; only the discovery fetch is stubbed, so no network is used. The
        # imports stay local so a moved FastMCP module fails this test, not the file.
        import fastmcp  # noqa: PLC0415
        from fastmcp.server.auth import OIDCProxy  # noqa: PLC0415
        from fastmcp.server.auth.oidc_proxy import OIDCConfiguration  # noqa: PLC0415

        # The proxy keeps its encrypted client store under FastMCP's home folder.
        monkeypatch.setattr(fastmcp.settings, "home", tmp_path)
        discovery = OIDCConfiguration.model_validate(
            {
                "issuer": "https://idp.example.com",
                "authorization_endpoint": "https://idp.example.com/authorize",
                "token_endpoint": "https://idp.example.com/token",
                "jwks_uri": "https://idp.example.com/jwks",
                "response_types_supported": ["code"],
                "subject_types_supported": ["public"],
                "id_token_signing_alg_values_supported": ["RS256"],
            }
        )
        config = ServerConfig(
            auth_mode="oidc",
            oidc_config_url="https://idp.example.com/.well-known/openid-configuration",
            oidc_client_id="my-client",
            oidc_client_secret="my-secret",  # noqa: S106
            oidc_base_url="https://mcp.example.com",
            oidc_audience="my-api",
        )
        with patch.object(OIDCProxy, "get_oidc_configuration", return_value=discovery) as fetch:
            result = create_auth_provider(config)

        assert isinstance(result, OIDCProxy)
        assert str(fetch.call_args.args[0]) == "https://idp.example.com/.well-known/openid-configuration"
        assert str(result.oidc_config.token_endpoint) == "https://idp.example.com/token"
        assert (tmp_path / "oauth-proxy").is_dir()


class TestAuthlibSurfaceUsedByFastMCP:
    """authlib is not imported by this server; FastMCP's OAuth proxy uses two of its symbols.

    Pinning them catches an authlib upgrade that moves or changes them before the
    OIDC flow fails at runtime. Imports stay local so a moved module fails only these tests.
    """

    def test_fastmcp_imports_resolve_to_authlib(self) -> None:
        from authlib.common.security import generate_token  # noqa: PLC0415
        from authlib.integrations.base_client import OAuthError  # noqa: PLC0415
        from fastmcp.server.auth.oauth_proxy import proxy, upstream  # noqa: PLC0415

        assert upstream.OAuthError is OAuthError
        assert proxy.generate_token is generate_token

    def test_oauth_error_keeps_rfc6749_fields(self) -> None:
        from authlib.integrations.base_client import OAuthError  # noqa: PLC0415

        error = OAuthError(error="invalid_grant", description="refresh token expired")
        assert error.error == "invalid_grant"
        assert error.description == "refresh token expired"

    def test_generated_pkce_verifier_is_rfc7636_valid(self) -> None:
        # FastMCP calls generate_token(48) for the PKCE code verifier, which RFC 7636
        # limits to 43-128 characters from the unreserved set.
        from authlib.common.security import generate_token  # noqa: PLC0415

        verifier = generate_token(48)
        assert len(verifier) == 48
        assert set(verifier) <= set(string.ascii_letters + string.digits + "-._~")


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
    def test_rejects_default_branch(self) -> None:
        with pytest.raises(ValueError, match="default branch 'main'"):
            assert_writable_branch("main", default_branch="main")

    def test_allows_non_default_branch(self) -> None:
        assert_writable_branch("mcp/session-20260420-abcd", default_branch="main")
        assert_writable_branch("feature/x", default_branch="main")

    def test_respects_custom_default(self) -> None:
        with pytest.raises(ValueError, match="default branch 'release'"):
            assert_writable_branch("release", default_branch="release")
        assert_writable_branch("main", default_branch="release")
