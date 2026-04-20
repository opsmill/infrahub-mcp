"""Tests for server configuration loading."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from infrahub_mcp.config import ServerConfig, load_config


class TestServerConfig:
    def test_defaults(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = ServerConfig()
        assert config.read_only is False
        assert config.branch_pattern == "mcp/session-{date}-{hex}"
        assert config.max_branch_retries == 5
        assert config.log_level_debug is False
        assert config.rate_limit_rps == pytest.approx(0.0)
        assert config.rate_limit_burst == 0
        assert config.retry_max_attempts == 0
        assert config.retry_base_delay == pytest.approx(1.0)
        assert config.cache_enabled is False
        assert config.cache_list_ttl == 300
        assert config.cache_read_ttl == 3600
        assert config.otel_enabled is False
        assert config.prometheus_enabled is False
        assert config.dereference_schemas is False
        assert config.ping_interval_ms == 0
        assert config.auth_scopes_write == "write"
        assert config.auth_mode == "none"
        assert not config.oidc_config_url
        assert not config.oidc_client_id
        assert not config.oidc_client_secret
        assert not config.oidc_base_url
        assert not config.oidc_audience
        assert config.oidc_user_claim == "email"
        assert config.token_passthrough_header == "Authorization"  # noqa: S105

    def test_frozen(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = ServerConfig()
        with pytest.raises(ValidationError):
            config.read_only = True  # type: ignore[misc]


class TestLoadConfig:  # noqa: PLR0904
    def test_defaults_no_env(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = load_config()
        assert config.read_only is False
        assert config.branch_pattern == "mcp/session-{date}-{hex}"
        assert config.max_branch_retries == 5
        assert config.log_level_debug is False

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
            with pytest.raises(ValidationError, match="valid integer"):
                load_config()

    def test_max_branch_retries_too_low(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_MAX_BRANCH_RETRIES": "0"}, clear=True):
            with pytest.raises(ValidationError, match="greater than or equal to 1"):
                load_config()

    def test_max_branch_retries_too_high(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_MAX_BRANCH_RETRIES": "100"}, clear=True):
            with pytest.raises(ValidationError, match="less than or equal to 20"):
                load_config()

    def test_log_level_debug(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_LOG_LEVEL": "debug"}, clear=True):
            config = load_config()
        assert config.log_level_debug is True

    def test_log_level_default(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_LOG_LEVEL": "info"}, clear=True):
            config = load_config()
        assert config.log_level_debug is False

    def test_log_level_invalid(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_LOG_LEVEL": "verbose"}, clear=True):
            with pytest.raises(ValidationError, match="INFRAHUB_MCP_LOG_LEVEL must be one of"):
                load_config()

    # --- Rate limiting ---

    def test_rate_limit_rps(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_RATE_LIMIT_RPS": "50"}, clear=True):
            config = load_config()
        assert config.rate_limit_rps == pytest.approx(50.0)

    def test_rate_limit_rps_invalid(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_RATE_LIMIT_RPS": "abc"}, clear=True):
            with pytest.raises(ValidationError, match="valid number"):
                load_config()

    def test_rate_limit_rps_negative(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_RATE_LIMIT_RPS": "-1"}, clear=True):
            with pytest.raises(ValidationError, match="greater than or equal to 0"):
                load_config()

    def test_rate_limit_burst(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_RATE_LIMIT_BURST": "100"}, clear=True):
            config = load_config()
        assert config.rate_limit_burst == 100

    def test_rate_limit_burst_negative(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_RATE_LIMIT_BURST": "-5"}, clear=True):
            with pytest.raises(ValidationError, match="greater than or equal to 0"):
                load_config()

    # --- Retry ---

    def test_retry_max_attempts(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_RETRY_MAX_ATTEMPTS": "3"}, clear=True):
            config = load_config()
        assert config.retry_max_attempts == 3

    def test_retry_max_attempts_negative(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_RETRY_MAX_ATTEMPTS": "-1"}, clear=True):
            with pytest.raises(ValidationError, match="greater than or equal to 0"):
                load_config()

    def test_retry_base_delay(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_RETRY_BASE_DELAY": "0.5"}, clear=True):
            config = load_config()
        assert config.retry_base_delay == pytest.approx(0.5)

    def test_retry_base_delay_zero(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_RETRY_BASE_DELAY": "0"}, clear=True):
            with pytest.raises(ValidationError, match="greater than 0"):
                load_config()

    # --- Cache ---

    def test_cache_enabled(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_CACHE_ENABLED": "true"}, clear=True):
            config = load_config()
        assert config.cache_enabled is True

    def test_cache_ttls(self) -> None:
        with patch.dict(
            os.environ,
            {"INFRAHUB_MCP_CACHE_LIST_TTL": "60", "INFRAHUB_MCP_CACHE_READ_TTL": "120"},
            clear=True,
        ):
            config = load_config()
        assert config.cache_list_ttl == 60
        assert config.cache_read_ttl == 120

    # --- Observability ---

    def test_otel_enabled(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_OTEL_ENABLED": "true"}, clear=True):
            config = load_config()
        assert config.otel_enabled is True

    def test_prometheus_enabled(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_PROMETHEUS_ENABLED": "true"}, clear=True):
            config = load_config()
        assert config.prometheus_enabled is True

    # --- Schema dereference ---

    def test_dereference_schemas(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_DEREFERENCE_SCHEMAS": "1"}, clear=True):
            config = load_config()
        assert config.dereference_schemas is True

    # --- Ping ---

    def test_ping_interval(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_PING_INTERVAL_MS": "5000"}, clear=True):
            config = load_config()
        assert config.ping_interval_ms == 5000

    def test_ping_interval_too_high(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_PING_INTERVAL_MS": "999999"}, clear=True):
            with pytest.raises(ValidationError, match="less than or equal to 300000"):
                load_config()

    def test_ping_interval_negative(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_PING_INTERVAL_MS": "-1"}, clear=True):
            with pytest.raises(ValidationError, match="greater than or equal to 0"):
                load_config()

    # --- Auth ---

    def test_auth_scopes_write(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_AUTH_SCOPES_WRITE": "write,admin"}, clear=True):
            config = load_config()
        assert config.auth_scopes_write == "write,admin"

    # --- Full config ---

    def test_all_env_vars(self) -> None:
        env = {
            "INFRAHUB_MCP_READ_ONLY": "true",
            "INFRAHUB_MCP_BRANCH_PATTERN": "test/{hex}",
            "INFRAHUB_MCP_MAX_BRANCH_RETRIES": "3",
            "INFRAHUB_MCP_LOG_LEVEL": "debug",
            "INFRAHUB_MCP_RATE_LIMIT_RPS": "10",
            "INFRAHUB_MCP_RATE_LIMIT_BURST": "20",
            "INFRAHUB_MCP_RETRY_MAX_ATTEMPTS": "3",
            "INFRAHUB_MCP_RETRY_BASE_DELAY": "0.5",
            "INFRAHUB_MCP_CACHE_ENABLED": "true",
            "INFRAHUB_MCP_CACHE_LIST_TTL": "60",
            "INFRAHUB_MCP_CACHE_READ_TTL": "120",
            "INFRAHUB_MCP_OTEL_ENABLED": "true",
            "INFRAHUB_MCP_PROMETHEUS_ENABLED": "true",
            "INFRAHUB_MCP_DEREFERENCE_SCHEMAS": "true",
            "INFRAHUB_MCP_PING_INTERVAL_MS": "5000",
            "INFRAHUB_MCP_AUTH_SCOPES_WRITE": "write",
            "INFRAHUB_MCP_AUTH_MODE": "oidc",
            "INFRAHUB_MCP_OIDC_CONFIG_URL": "https://idp.example.com/.well-known/openid-configuration",
            "INFRAHUB_MCP_OIDC_CLIENT_ID": "my-client",
            "INFRAHUB_MCP_OIDC_CLIENT_SECRET": "s3cret",
            "INFRAHUB_MCP_OIDC_BASE_URL": "https://mcp.example.com",
            "INFRAHUB_MCP_OIDC_AUDIENCE": "infrahub",
            "INFRAHUB_MCP_OIDC_USER_CLAIM": "sub",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()

        assert config.read_only is True
        assert config.branch_pattern == "test/{hex}"
        assert config.max_branch_retries == 3
        assert config.log_level_debug is True
        assert config.rate_limit_rps == pytest.approx(10.0)
        assert config.rate_limit_burst == 20
        assert config.retry_max_attempts == 3
        assert config.retry_base_delay == pytest.approx(0.5)
        assert config.cache_enabled is True
        assert config.cache_list_ttl == 60
        assert config.cache_read_ttl == 120
        assert config.otel_enabled is True
        assert config.prometheus_enabled is True
        assert config.dereference_schemas is True
        assert config.ping_interval_ms == 5000
        assert config.auth_scopes_write == "write"
        assert config.auth_mode == "oidc"
        assert config.oidc_config_url == "https://idp.example.com/.well-known/openid-configuration"
        assert config.oidc_client_id == "my-client"
        assert config.oidc_client_secret == "s3cret"  # noqa: S105
        assert config.oidc_base_url == "https://mcp.example.com"
        assert config.oidc_audience == "infrahub"
        assert config.oidc_user_claim == "sub"


class TestAuthModeConfig:
    def test_auth_mode_default_none(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = load_config()
        assert config.auth_mode == "none"

    def test_auth_mode_none_explicit(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_AUTH_MODE": "none"}, clear=True):
            config = load_config()
        assert config.auth_mode == "none"

    def test_auth_mode_oidc_valid(self) -> None:
        env = {
            "INFRAHUB_MCP_AUTH_MODE": "oidc",
            "INFRAHUB_MCP_OIDC_CONFIG_URL": "https://accounts.google.com/.well-known/openid-configuration",
            "INFRAHUB_MCP_OIDC_CLIENT_ID": "my-client-id",
            "INFRAHUB_MCP_OIDC_BASE_URL": "https://mcp.example.com",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()
        assert config.auth_mode == "oidc"
        assert config.oidc_config_url == "https://accounts.google.com/.well-known/openid-configuration"
        assert config.oidc_client_id == "my-client-id"
        assert config.oidc_base_url == "https://mcp.example.com"

    def test_auth_mode_oidc_case_insensitive(self) -> None:
        env = {
            "INFRAHUB_MCP_AUTH_MODE": "OIDC",
            "INFRAHUB_MCP_OIDC_CONFIG_URL": "https://example.com/.well-known/openid-configuration",
            "INFRAHUB_MCP_OIDC_CLIENT_ID": "id",
            "INFRAHUB_MCP_OIDC_BASE_URL": "https://mcp.example.com",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()
        assert config.auth_mode == "oidc"

    def test_auth_mode_invalid_value(self) -> None:
        with patch.dict(os.environ, {"INFRAHUB_MCP_AUTH_MODE": "saml"}, clear=True):
            with pytest.raises(ValidationError, match="Input should be 'none', 'oidc'"):
                load_config()

    def test_auth_mode_oidc_missing_config_url(self) -> None:
        env = {
            "INFRAHUB_MCP_AUTH_MODE": "oidc",
            "INFRAHUB_MCP_OIDC_CLIENT_ID": "id",
            "INFRAHUB_MCP_OIDC_BASE_URL": "https://mcp.example.com",
        }
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="INFRAHUB_MCP_OIDC_CONFIG_URL"):
                load_config()

    def test_auth_mode_oidc_missing_client_id(self) -> None:
        env = {
            "INFRAHUB_MCP_AUTH_MODE": "oidc",
            "INFRAHUB_MCP_OIDC_CONFIG_URL": "https://example.com/.well-known/openid-configuration",
            "INFRAHUB_MCP_OIDC_BASE_URL": "https://mcp.example.com",
        }
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="INFRAHUB_MCP_OIDC_CLIENT_ID"):
                load_config()

    def test_auth_mode_oidc_missing_base_url(self) -> None:
        env = {
            "INFRAHUB_MCP_AUTH_MODE": "oidc",
            "INFRAHUB_MCP_OIDC_CONFIG_URL": "https://example.com/.well-known/openid-configuration",
            "INFRAHUB_MCP_OIDC_CLIENT_ID": "id",
        }
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ValueError, match="INFRAHUB_MCP_OIDC_BASE_URL"):
                load_config()

    def test_auth_mode_oidc_optional_fields(self) -> None:
        env = {
            "INFRAHUB_MCP_AUTH_MODE": "oidc",
            "INFRAHUB_MCP_OIDC_CONFIG_URL": "https://example.com/.well-known/openid-configuration",
            "INFRAHUB_MCP_OIDC_CLIENT_ID": "id",
            "INFRAHUB_MCP_OIDC_BASE_URL": "https://mcp.example.com",
            "INFRAHUB_MCP_OIDC_CLIENT_SECRET": "secret",
            "INFRAHUB_MCP_OIDC_AUDIENCE": "my-audience",
            "INFRAHUB_MCP_OIDC_USER_CLAIM": "preferred_username",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()
        assert config.oidc_client_secret == "secret"  # noqa: S105
        assert config.oidc_audience == "my-audience"
        assert config.oidc_user_claim == "preferred_username"

    def test_auth_mode_token_passthrough_valid(self) -> None:
        env = {
            "INFRAHUB_MCP_AUTH_MODE": "token-passthrough",
            "INFRAHUB_ADDRESS": "http://localhost:8000",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()
        assert config.auth_mode == "token-passthrough"

    def test_auth_mode_token_passthrough_custom_header(self) -> None:
        env = {
            "INFRAHUB_MCP_AUTH_MODE": "token-passthrough",
            "INFRAHUB_ADDRESS": "http://localhost:8000",
            "INFRAHUB_MCP_TOKEN_PASSTHROUGH_HEADER": "X-Infrahub-Token",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()
        assert config.token_passthrough_header == "X-Infrahub-Token"  # noqa: S105

    def test_auth_mode_token_passthrough_without_address_loads(self) -> None:
        """Passthrough modes defer the INFRAHUB_ADDRESS check to request time."""
        env = {
            "INFRAHUB_MCP_AUTH_MODE": "token-passthrough",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()
        assert config.auth_mode == "token-passthrough"

    def test_auth_mode_none_ignores_oidc_fields(self) -> None:
        env = {
            "INFRAHUB_MCP_AUTH_MODE": "none",
            "INFRAHUB_MCP_OIDC_CONFIG_URL": "https://example.com/.well-known/openid-configuration",
        }
        with patch.dict(os.environ, env, clear=True):
            config = load_config()
        assert config.auth_mode == "none"
        assert config.oidc_config_url == "https://example.com/.well-known/openid-configuration"
