"""Server configuration loaded from environment variables via pydantic-settings."""

from __future__ import annotations

import string
from typing import Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from infrahub_mcp.constants import (
    _ALLOWED_PLACEHOLDERS,
    AUTH_MODE_OIDC,
)

AuthMode = Literal["none", "oidc", "token-passthrough", "basic-passthrough"]

_VALID_LOG_LEVELS = {"debug", "info", "warning", "error"}
_BRANCH_PATTERN_HELP = "Allowed placeholders are {date}, {hex}, {user}."


class ServerConfig(BaseSettings):
    """Immutable server configuration loaded from ``INFRAHUB_MCP_*`` environment variables.

    Each field is validated at construction time — instantiation fails fast
    with a clear message when an environment variable is malformed or a
    required combination is missing (e.g., OIDC mode without a config URL).

    Attributes:
        read_only: When True, write tools are hidden and GraphQL mutations are blocked.
        branch_pattern: Naming pattern for session branches. Supports ``{date}``, ``{hex}``,
            and ``{user}`` placeholders. If no placeholders are present it is treated as a
            fixed branch name. Defaults to ``mcp/session-{date}-{hex}``.
        max_branch_retries: Max collision retries for branch name generation (1-20).
        log_level: Logging verbosity (``debug``, ``info``, ``warning``, ``error``).
        rate_limit_rps: Max sustained requests per second (0 disables).
        rate_limit_burst: Token-bucket burst capacity (0 = auto, 2x ``rate_limit_rps``).
        retry_max_attempts: Max retry attempts for transient failures (0 disables).
        retry_base_delay: Initial delay between retries, in seconds.
        cache_enabled: Enable response caching for schema/list operations.
        cache_list_ttl: TTL in seconds for list operations (tools, resources, prompts).
        cache_read_ttl: TTL in seconds for read-resource and cacheable tool calls.
        otel_enabled: Enable OpenTelemetry tracing spans.
        prometheus_enabled: Expose Prometheus-format metrics at ``/metrics``.
        dereference_schemas: Dereference ``$ref`` in JSON schemas for client compatibility.
        ping_interval_ms: Ping interval in milliseconds for HTTP sessions (0 disables,
            max 300 000).
        auth_scopes_write: OAuth scopes required for write operations (comma-separated).
            Defaults to ``write``.
        auth_mode: Authentication mode (``none``, ``oidc``, ``token-passthrough``, or
            ``basic-passthrough``).
        oidc_config_url: OIDC discovery URL (required when ``auth_mode=oidc``).
        oidc_client_id: OAuth client ID (required when ``auth_mode=oidc``).
        oidc_client_secret: OAuth client secret (optional — omit for PKCE).
        oidc_base_url: Public URL where the MCP server is reachable (required when
            ``auth_mode=oidc``).
        oidc_audience: Token audience claim (optional).
        oidc_user_claim: JWT claim used for user identity (defaults to ``email``).
        token_passthrough_header: HTTP header carrying the per-request credential
            (Bearer token or Basic user:pass) when ``auth_mode`` is ``token-passthrough``
            or ``basic-passthrough``.
    """

    model_config = SettingsConfigDict(
        env_prefix="INFRAHUB_MCP_",
        case_sensitive=False,
        frozen=True,
        extra="ignore",
        populate_by_name=True,
    )

    read_only: bool = False
    branch_pattern: str = "mcp/session-{date}-{hex}"
    max_branch_retries: int = Field(default=5, ge=1, le=20)
    log_level: str = Field(
        default="info",
        validation_alias=AliasChoices("log_level", "INFRAHUB_MCP_LOG_LEVEL"),
    )
    rate_limit_rps: float = Field(default=0.0, ge=0.0, le=10_000.0, allow_inf_nan=False)
    rate_limit_burst: int = Field(default=0, ge=0)
    retry_max_attempts: int = Field(default=0, ge=0)
    retry_base_delay: float = Field(default=1.0, gt=0.0, allow_inf_nan=False)
    cache_enabled: bool = False
    cache_list_ttl: int = Field(default=300, ge=1)
    cache_read_ttl: int = Field(default=3600, ge=1)
    otel_enabled: bool = False
    prometheus_enabled: bool = False
    dereference_schemas: bool = False
    ping_interval_ms: int = Field(default=0, ge=0, le=300_000)
    auth_scopes_write: str = "write"
    auth_mode: AuthMode = "none"
    oidc_config_url: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_base_url: str = ""
    oidc_audience: str = ""
    oidc_user_claim: str = "email"
    token_passthrough_header: str = "Authorization"  # noqa: S105

    @property
    def log_level_debug(self) -> bool:
        """True when ``INFRAHUB_MCP_LOG_LEVEL=debug``."""
        return self.log_level.lower() == "debug"

    @field_validator("log_level", mode="before")
    @classmethod
    def _validate_log_level(cls, raw: object) -> str:
        value = str(raw).strip().lower()
        if value not in _VALID_LOG_LEVELS:
            msg = f"INFRAHUB_MCP_LOG_LEVEL must be one of {sorted(_VALID_LOG_LEVELS)}, got {value!r}."
            raise ValueError(msg)
        return value

    @field_validator("auth_mode", mode="before")
    @classmethod
    def _normalize_auth_mode(cls, raw: object) -> str:
        """Strip + lowercase the raw env value; Literal validation handles unknown values."""
        return str(raw).strip().lower()

    @field_validator("branch_pattern")
    @classmethod
    def _validate_branch_pattern(cls, pattern: str) -> str:
        try:
            parsed = list(string.Formatter().parse(pattern))
        except (ValueError, IndexError) as exc:
            msg = f"INFRAHUB_MCP_BRANCH_PATTERN has invalid syntax: {pattern!r}. {_BRANCH_PATTERN_HELP} Error: {exc}"
            raise ValueError(msg) from exc

        fields: list[str] = []
        for _, field_name, format_spec, conversion in parsed:
            if field_name is None:
                continue
            if format_spec or conversion is not None:
                msg = (
                    f"INFRAHUB_MCP_BRANCH_PATTERN must not use format specifiers or conversions: "
                    f"{pattern!r}. {_BRANCH_PATTERN_HELP} (no :spec, !conversion)"
                )
                raise ValueError(msg)
            fields.append(field_name)

        bad = sorted(set(fields) - _ALLOWED_PLACEHOLDERS)
        if bad:
            msg = (
                f"INFRAHUB_MCP_BRANCH_PATTERN contains unsupported placeholders: {pattern!r}. "
                f"Unknown: {bad}. {_BRANCH_PATTERN_HELP}"
            )
            raise ValueError(msg)
        return pattern


def _validate_auth_requirements(config: ServerConfig) -> None:
    """Enforce cross-field auth requirements that depend on external env vars.

    Not a pydantic model validator so that unit tests can construct
    ``ServerConfig(auth_mode="oidc")`` without having to stub every
    required OIDC field — the env-driven requirement lives at the
    :func:`load_config` boundary, not inside the model.
    """
    if config.auth_mode == AUTH_MODE_OIDC:
        missing = [
            name
            for name, value in (
                ("INFRAHUB_MCP_OIDC_CONFIG_URL", config.oidc_config_url),
                ("INFRAHUB_MCP_OIDC_CLIENT_ID", config.oidc_client_id),
                ("INFRAHUB_MCP_OIDC_BASE_URL", config.oidc_base_url),
            )
            if not value.strip()
        ]
        if missing:
            msg = (
                f"OIDC auth mode requires these environment variables: {', '.join(missing)}. "
                "See https://docs.opsmill.com for configuration details."
            )
            raise ValueError(msg)


def load_config() -> ServerConfig:
    """Load and validate server configuration from environment variables."""
    config = ServerConfig()
    _validate_auth_requirements(config)
    return config
