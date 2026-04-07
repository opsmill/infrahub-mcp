"""Authentication provider factory and user identity helpers."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from infrahub_mcp.constants import AUTH_MODE_OIDC

if TYPE_CHECKING:
    from fastmcp.server.auth import OIDCProxy

    from infrahub_mcp.config import ServerConfig

logger = logging.getLogger(__name__)


def create_auth_provider(config: ServerConfig) -> OIDCProxy | None:
    """Build an OIDCProxy from config, or return None for mode=none.

    The OIDCProxy handles the full OAuth 2.0 / OIDC authorization code flow:
    token exchange, JWT verification, and scope extraction. It is passed to
    ``FastMCP(auth=...)`` at construction time.

    The OIDC token is for MCP-level access control only — Infrahub API calls
    still use the shared env var credentials.
    """
    if config.auth_mode != AUTH_MODE_OIDC:
        return None

    from fastmcp.server.auth import OIDCProxy  # noqa: PLC0415

    kwargs: dict[str, object] = {
        "config_url": config.oidc_config_url,
        "client_id": config.oidc_client_id,
        "base_url": config.oidc_base_url,
    }
    if config.oidc_client_secret:
        kwargs["client_secret"] = config.oidc_client_secret
    if config.oidc_audience:
        kwargs["audience"] = config.oidc_audience

    logger.info(
        "oidc_auth enabled=true config_url=%s client_id=%s",
        config.oidc_config_url,
        config.oidc_client_id,
    )
    return OIDCProxy(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# User identity from OIDC token
# ---------------------------------------------------------------------------

# Branch names: allow alphanumeric, hyphens, underscores, dots, slashes
_BRANCH_UNSAFE = re.compile(r"[^a-zA-Z0-9._/-]")
_COLLAPSE_HYPHENS = re.compile(r"-{2,}")


def sanitize_user_for_branch(raw: str) -> str:
    """Sanitize a user identity string for use in git branch names.

    Replaces characters not allowed in branch names with hyphens,
    collapses runs of hyphens, and strips leading/trailing hyphens.
    """
    cleaned = _BRANCH_UNSAFE.sub("-", raw)
    cleaned = _COLLAPSE_HYPHENS.sub("-", cleaned)
    return cleaned.strip("-") or "anonymous"


def get_user_from_token(claim: str = "email") -> str:
    """Extract user identity from the current OIDC access token.

    Uses FastMCP's ``get_access_token()`` to read the token from the
    request context. Returns ``"anonymous"`` when no token is available
    (e.g., stdio transport or mode=none).

    Args:
        claim: JWT claim to use for identity (default: ``email``).
    """
    try:
        from fastmcp.server.middleware.authorization import get_access_token  # noqa: PLC0415

        token = get_access_token()
        if token is not None and token.claims:
            value = token.claims.get(claim) or token.claims.get("sub")
            if value:
                return sanitize_user_for_branch(str(value))
    except Exception:
        logger.debug("Failed to extract user from OIDC token", exc_info=True)
    return "anonymous"
