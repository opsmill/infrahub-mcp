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
    """

    read_only: bool = False
    branch_pattern: str = "mcp/session-{date}-{hex}"
    max_branch_retries: int = 5
    log_level_debug: bool = False


_MAX_BRANCH_RETRIES_LIMIT = 20


def load_config() -> ServerConfig:
    """Load server configuration from environment variables.

    Environment variables:
        INFRAHUB_MCP_READ_ONLY: Set to ``true`` to disable write operations.
        INFRAHUB_MCP_BRANCH_PATTERN: Branch naming pattern or fixed name.
    """
    read_only = os.environ.get("INFRAHUB_MCP_READ_ONLY", "false").lower() in {"true", "1", "yes"}
    branch_pattern = os.environ.get("INFRAHUB_MCP_BRANCH_PATTERN", "mcp/session-{date}-{hex}")
    log_level_debug = os.environ.get("INFRAHUB_MCP_LOG_LEVEL", "info").lower() == "debug"

    try:
        max_branch_retries = int(os.environ.get("INFRAHUB_MCP_MAX_BRANCH_RETRIES", "5"))
    except ValueError as exc:
        msg = "INFRAHUB_MCP_MAX_BRANCH_RETRIES must be an integer."
        raise ValueError(msg) from exc

    if not 1 <= max_branch_retries <= _MAX_BRANCH_RETRIES_LIMIT:
        msg = f"INFRAHUB_MCP_MAX_BRANCH_RETRIES must be between 1 and {_MAX_BRANCH_RETRIES_LIMIT}, got {max_branch_retries}."
        raise ValueError(msg)

    return ServerConfig(
        read_only=read_only,
        branch_pattern=branch_pattern,
        max_branch_retries=max_branch_retries,
        log_level_debug=log_level_debug,
    )
