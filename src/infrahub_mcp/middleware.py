"""Middleware stack for the Infrahub MCP server.

Scaffold registered from ``server.py`` via :func:`configure_middleware`. Each
section below is populated incrementally by the follow-up PRs that make up
the middleware rollout (see ``docs/specs/INFP-411.md``). Shipping the scaffold
first lets later slices add their middleware without restructuring server.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastmcp import FastMCP

    from infrahub_mcp.config import ServerConfig


# ---------------------------------------------------------------------------
# Safety (read-only + auth)
# ---------------------------------------------------------------------------
# Populated by PR 2 (read-only) and PR 3 (auth).


# ---------------------------------------------------------------------------
# Production hardening (rate limit, caching, retry, error handling)
# ---------------------------------------------------------------------------
# Populated by PR 4.


# ---------------------------------------------------------------------------
# Observability (request IDs, structured logging, timing, tracing, audit)
# ---------------------------------------------------------------------------
# Populated by PR 5.


# ---------------------------------------------------------------------------
# Compatibility (dereference $ref, ping keepalive)
# ---------------------------------------------------------------------------
# Populated by PR 6.


def configure_middleware(mcp: FastMCP, config: ServerConfig) -> None:  # noqa: ARG001
    """Register middleware on the FastMCP instance.

    No-op in this PR — the scaffold exists so later slices add their
    ``mcp.add_middleware(...)`` calls in one place without touching
    ``server.py``.
    """
    return
