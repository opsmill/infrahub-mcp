"""Centralized server configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ServerConfig:
    """Immutable server configuration parsed from environment variables.

    Attributes:
        read_only: When True, write tools are hidden and GraphQL mutations are blocked.
        branch_pattern: Naming pattern for session branches. Supports {date}, {hex},
            {user} placeholders. If no placeholders are present, treated as a fixed
            branch name. Defaults to ``mcp/session-{date}-{hex}``.
        max_branch_retries: Max collision retries for branch name generation.
        log_level_debug: Enable verbose debug logging.
        rate_limit_rps: Max sustained requests per second (0 = disabled).
        rate_limit_burst: Token bucket burst capacity (0 = auto: 2x rate_limit_rps).
        retry_max_attempts: Max retry attempts for transient failures (0 = disabled).
        retry_base_delay: Initial delay between retries in seconds.
        cache_enabled: Enable response caching for schema/list operations.
        cache_list_ttl: TTL in seconds for list operations (tools, resources, prompts).
        cache_read_ttl: TTL in seconds for read operations (resources, prompts, tools).
        otel_enabled: Enable OpenTelemetry tracing spans.
        prometheus_enabled: Expose Prometheus-format metrics at /metrics.
        dereference_schemas: Dereference $ref in JSON schemas for client compatibility.
        ping_interval_ms: Ping interval in milliseconds for HTTP sessions (0 = disabled).
        auth_scopes_write: OAuth scopes required for write operations (comma-separated).
    """

    read_only: bool = False
    branch_pattern: str = "mcp/session-{date}-{hex}"
    max_branch_retries: int = 5
    log_level_debug: bool = False
    rate_limit_rps: float = 0.0
    rate_limit_burst: int = 0
    retry_max_attempts: int = 0
    retry_base_delay: float = 1.0
    cache_enabled: bool = False
    cache_list_ttl: int = 300
    cache_read_ttl: int = 3600
    otel_enabled: bool = False
    prometheus_enabled: bool = False
    dereference_schemas: bool = False
    ping_interval_ms: int = 0
    auth_scopes_write: str = ""


_MAX_BRANCH_RETRIES_LIMIT = 20
_MAX_RATE_LIMIT_RPS = 10000.0
_MAX_PING_INTERVAL_MS = 300_000


def load_config() -> ServerConfig:
    """Load server configuration from environment variables.

    Environment variables:
        INFRAHUB_MCP_READ_ONLY: Set to ``true`` to disable write operations.
        INFRAHUB_MCP_BRANCH_PATTERN: Branch naming pattern or fixed name.
        INFRAHUB_MCP_LOG_LEVEL: Set to ``debug`` for verbose logging.
        INFRAHUB_MCP_MAX_BRANCH_RETRIES: Max collision retries (1-20).
        INFRAHUB_MCP_RATE_LIMIT_RPS: Requests per second (0 = disabled).
        INFRAHUB_MCP_RATE_LIMIT_BURST: Token bucket burst capacity.
        INFRAHUB_MCP_RETRY_MAX_ATTEMPTS: Max retry attempts (0 = disabled).
        INFRAHUB_MCP_RETRY_BASE_DELAY: Initial retry delay in seconds.
        INFRAHUB_MCP_CACHE_ENABLED: Enable response caching (true/false).
        INFRAHUB_MCP_CACHE_LIST_TTL: TTL for list operations in seconds.
        INFRAHUB_MCP_CACHE_READ_TTL: TTL for read operations in seconds.
        INFRAHUB_MCP_OTEL_ENABLED: Enable OpenTelemetry tracing (true/false).
        INFRAHUB_MCP_PROMETHEUS_ENABLED: Enable Prometheus metrics format (true/false).
        INFRAHUB_MCP_DEREFERENCE_SCHEMAS: Dereference $ref in schemas (true/false).
        INFRAHUB_MCP_PING_INTERVAL_MS: Ping interval in ms (0 = disabled).
        INFRAHUB_MCP_AUTH_SCOPES_WRITE: OAuth scopes for write ops (comma-separated).
    """
    _validate_branch_retries()
    _validate_rate_limit()
    _validate_retry()
    _validate_ping_interval()

    return ServerConfig(
        read_only=_parse_bool("INFRAHUB_MCP_READ_ONLY"),
        branch_pattern=os.environ.get("INFRAHUB_MCP_BRANCH_PATTERN", "mcp/session-{date}-{hex}"),
        max_branch_retries=_parse_int("INFRAHUB_MCP_MAX_BRANCH_RETRIES", default=5),
        log_level_debug=os.environ.get("INFRAHUB_MCP_LOG_LEVEL", "info").lower() == "debug",
        rate_limit_rps=_parse_float("INFRAHUB_MCP_RATE_LIMIT_RPS", default=0.0),
        rate_limit_burst=_parse_int("INFRAHUB_MCP_RATE_LIMIT_BURST", default=0),
        retry_max_attempts=_parse_int("INFRAHUB_MCP_RETRY_MAX_ATTEMPTS", default=0),
        retry_base_delay=_parse_float("INFRAHUB_MCP_RETRY_BASE_DELAY", default=1.0),
        cache_enabled=_parse_bool("INFRAHUB_MCP_CACHE_ENABLED"),
        cache_list_ttl=_parse_int("INFRAHUB_MCP_CACHE_LIST_TTL", default=300),
        cache_read_ttl=_parse_int("INFRAHUB_MCP_CACHE_READ_TTL", default=3600),
        otel_enabled=_parse_bool("INFRAHUB_MCP_OTEL_ENABLED"),
        prometheus_enabled=_parse_bool("INFRAHUB_MCP_PROMETHEUS_ENABLED"),
        dereference_schemas=_parse_bool("INFRAHUB_MCP_DEREFERENCE_SCHEMAS"),
        ping_interval_ms=_parse_int("INFRAHUB_MCP_PING_INTERVAL_MS", default=0),
        auth_scopes_write=os.environ.get("INFRAHUB_MCP_AUTH_SCOPES_WRITE", ""),
    )


def _validate_branch_retries() -> None:
    """Validate INFRAHUB_MCP_MAX_BRANCH_RETRIES range."""
    val = _parse_int("INFRAHUB_MCP_MAX_BRANCH_RETRIES", default=5)
    if not 1 <= val <= _MAX_BRANCH_RETRIES_LIMIT:
        msg = f"INFRAHUB_MCP_MAX_BRANCH_RETRIES must be between 1 and {_MAX_BRANCH_RETRIES_LIMIT}, got {val}."
        raise ValueError(msg)


def _validate_rate_limit() -> None:
    """Validate rate limit env vars."""
    rps = _parse_float("INFRAHUB_MCP_RATE_LIMIT_RPS", default=0.0)
    if rps < 0 or rps > _MAX_RATE_LIMIT_RPS:
        msg = f"INFRAHUB_MCP_RATE_LIMIT_RPS must be between 0 and {_MAX_RATE_LIMIT_RPS}, got {rps}."
        raise ValueError(msg)

    burst = _parse_int("INFRAHUB_MCP_RATE_LIMIT_BURST", default=0)
    if burst < 0:
        msg = f"INFRAHUB_MCP_RATE_LIMIT_BURST must be non-negative, got {burst}."
        raise ValueError(msg)


def _validate_retry() -> None:
    """Validate retry env vars."""
    attempts = _parse_int("INFRAHUB_MCP_RETRY_MAX_ATTEMPTS", default=0)
    if attempts < 0:
        msg = f"INFRAHUB_MCP_RETRY_MAX_ATTEMPTS must be non-negative, got {attempts}."
        raise ValueError(msg)

    delay = _parse_float("INFRAHUB_MCP_RETRY_BASE_DELAY", default=1.0)
    if delay <= 0:
        msg = f"INFRAHUB_MCP_RETRY_BASE_DELAY must be positive, got {delay}."
        raise ValueError(msg)


def _validate_ping_interval() -> None:
    """Validate INFRAHUB_MCP_PING_INTERVAL_MS range."""
    val = _parse_int("INFRAHUB_MCP_PING_INTERVAL_MS", default=0)
    if val < 0 or (val > 0 and val > _MAX_PING_INTERVAL_MS):
        msg = f"INFRAHUB_MCP_PING_INTERVAL_MS must be 0 (disabled) or between 1 and {_MAX_PING_INTERVAL_MS}, got {val}."
        raise ValueError(msg)


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_bool(env_var: str) -> bool:
    """Parse a boolean environment variable."""
    return os.environ.get(env_var, "false").lower() in {"true", "1", "yes"}


def _parse_int(env_var: str, *, default: int) -> int:
    """Parse an integer environment variable with a default."""
    raw = os.environ.get(env_var)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        msg = f"{env_var} must be an integer."
        raise ValueError(msg) from exc


def _parse_float(env_var: str, *, default: float) -> float:
    """Parse a float environment variable with a default."""
    raw = os.environ.get(env_var)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        msg = f"{env_var} must be a number."
        raise ValueError(msg) from exc
