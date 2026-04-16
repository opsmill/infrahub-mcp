"""Centralized server configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ServerConfig:
    """Immutable server configuration parsed from environment variables.

    Attributes:
        max_query_depth: Maximum relationship traversal depth when returning schema
            details. ``0`` disables expansion, ``5`` is the upper limit.
    """

    max_query_depth: int = 2


_MAX_QUERY_DEPTH_LIMIT = 5


def load_config() -> ServerConfig:
    """Load server configuration from environment variables.

    Environment variables:
        INFRAHUB_MCP_MAX_QUERY_DEPTH: Max relationship depth in schema responses (0-5, default 2).
    """
    _validate_query_depth()

    return ServerConfig(
        max_query_depth=_parse_int("INFRAHUB_MCP_MAX_QUERY_DEPTH", default=2),
    )


def _validate_query_depth() -> None:
    """Validate INFRAHUB_MCP_MAX_QUERY_DEPTH range."""
    val = _parse_int("INFRAHUB_MCP_MAX_QUERY_DEPTH", default=2)
    if not 0 <= val <= _MAX_QUERY_DEPTH_LIMIT:
        msg = f"INFRAHUB_MCP_MAX_QUERY_DEPTH must be between 0 and {_MAX_QUERY_DEPTH_LIMIT}, got {val}."
        raise ValueError(msg)


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
