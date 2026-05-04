"""CLI entry point for the infrahub-mcp server."""

import argparse
from typing import Any

from infrahub_mcp.constants import AUTH_MODE_BASIC_PASSTHROUGH, AUTH_MODE_OIDC, AUTH_MODE_TOKEN_PASSTHROUGH
from infrahub_mcp.server import _config, get_asgi_middleware, mcp


def main() -> None:
    """Entry point for the infrahub-mcp CLI command."""
    parser = argparse.ArgumentParser(description="Infrahub MCP Server")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "streamable-http"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    if (
        _config.auth_mode in {AUTH_MODE_OIDC, AUTH_MODE_TOKEN_PASSTHROUGH, AUTH_MODE_BASIC_PASSTHROUGH}
        and args.transport == "stdio"
    ):
        msg = f"Auth mode {_config.auth_mode!r} requires streamable-http transport. Stdio has no HTTP headers."
        raise SystemExit(msg)

    kwargs: dict[str, Any] = {"transport": args.transport, "host": args.host, "port": args.port}
    asgi_mw = get_asgi_middleware()
    if asgi_mw and args.transport == "streamable-http":
        kwargs["middleware"] = asgi_mw
    mcp.run(**kwargs)
