"""Authentication provider factory and user identity helpers."""

from __future__ import annotations

import logging
import re
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Any

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

    Returns:
        OIDCProxy when auth_mode is ``oidc``, otherwise ``None``.
    """
    if config.auth_mode != AUTH_MODE_OIDC:
        return None

    from fastmcp.server.auth import OIDCProxy  # noqa: PLC0415

    kwargs: dict[str, Any] = {
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
    return OIDCProxy(**kwargs)


# ---------------------------------------------------------------------------
# Token passthrough — per-request ContextVar
# ---------------------------------------------------------------------------

_passthrough_token: ContextVar[str | None] = ContextVar("_passthrough_token", default=None)
_passthrough_basic: ContextVar[tuple[str, str] | None] = ContextVar("_passthrough_basic", default=None)


def set_passthrough_token(token: str) -> Token[str | None]:
    """Store the passthrough token for the current async task.

    Returns a :class:`contextvars.Token` that **must** be passed to
    :func:`reset_passthrough_token` when the request is done so that
    the value does not leak to subsequent requests sharing the same
    async context.
    """
    return _passthrough_token.set(token)


def reset_passthrough_token(token: Token[str | None]) -> None:
    """Restore the passthrough ContextVar to its previous value."""
    _passthrough_token.reset(token)


def get_passthrough_token() -> str | None:
    """Read the passthrough token for the current async task."""
    return _passthrough_token.get()


def set_passthrough_basic(credentials: tuple[str, str]) -> Token[tuple[str, str] | None]:
    """Store the passthrough (username, password) pair for the current async task."""
    return _passthrough_basic.set(credentials)


def reset_passthrough_basic(token: Token[tuple[str, str] | None]) -> None:
    """Restore the basic-passthrough ContextVar to its previous value."""
    _passthrough_basic.reset(token)


def get_passthrough_basic() -> tuple[str, str] | None:
    """Read the passthrough (username, password) pair for the current async task."""
    return _passthrough_basic.get()


# ---------------------------------------------------------------------------
# User identity from OIDC token
# ---------------------------------------------------------------------------

# Branch names: allow alphanumeric, hyphens, underscores, dots, slashes
_BRANCH_UNSAFE = re.compile(r"[^a-zA-Z0-9._/-]")
_COLLAPSE_HYPHENS = re.compile(r"-{2,}")
_DOUBLE_DOT = re.compile(r"\.{2,}")
_DOUBLE_SLASH = re.compile(r"/{2,}")
_SLASH_DOT = re.compile(r"/\.")
_DOT_LOCK_END = re.compile(r"\.lock$")


def assert_writable_branch(branch: str, *, default_branch: str) -> None:
    """Reject writes targeting the Infrahub default branch.

    Session branches (``mcp/session-...``) and feature branches bypass this
    guard — only the instance's default branch (typically ``main``) is
    blocked. The default branch is resolved from the Infrahub server via
    ``client.branch.all()`` and cached on the ``AppContext``.
    """
    if branch == default_branch:
        msg = (
            f"Writes to the default branch {branch!r} are not allowed. "
            "Use the auto-created session branch or a feature branch; "
            "merge via propose_changes."
        )
        raise ValueError(msg)


def sanitize_user_for_branch(raw: str) -> str:
    """Sanitize a user identity string for use in git branch names.

    Applies the rules from ``git check-ref-format``:
    - Replace characters not in ``[a-zA-Z0-9._/-]`` with hyphens.
    - Replace ``..`` sequences (forbidden in refs) with a single dot.
    - Replace ``/.`` sequences with ``/`` (refs cannot have components starting with ``.``).
    - Replace ``//`` sequences with a single slash (runs after ``/.`` removal
      so collapsed slashes can't be reintroduced).
    - Strip a trailing ``.lock`` suffix.
    - Strip leading/trailing dots, slashes, and hyphens.
    - Collapse runs of hyphens.

    Returns:
        Sanitized string safe for branch names, or ``"anonymous"`` if empty.
    """
    cleaned = _BRANCH_UNSAFE.sub("-", raw)
    cleaned = _DOUBLE_DOT.sub(".", cleaned)
    cleaned = _SLASH_DOT.sub("/", cleaned)
    cleaned = _DOUBLE_SLASH.sub("/", cleaned)
    cleaned = _DOT_LOCK_END.sub("", cleaned)
    cleaned = _COLLAPSE_HYPHENS.sub("-", cleaned)
    return cleaned.strip("-./") or "anonymous"


def get_user_from_token(claim: str = "email") -> str:
    """Extract user identity from the current OIDC access token.

    Uses FastMCP's ``get_access_token()`` to read the token from the
    request context. Returns ``"anonymous"`` when no token is available
    (e.g., stdio transport or mode=none).

    Args:
        claim: JWT claim to use for identity (default: ``email``).

    Returns:
        Sanitized user identity string, or ``"anonymous"`` when unavailable.
    """
    try:
        from fastmcp.server.middleware.authorization import get_access_token  # noqa: PLC0415

        token = get_access_token()
        if token is not None and token.claims:
            value = token.claims.get(claim) or token.claims.get("sub")
            if value:
                return sanitize_user_for_branch(str(value))
    except (ImportError, AttributeError, KeyError, TypeError):
        logger.debug("Failed to extract user from OIDC token", exc_info=True)
    return "anonymous"
