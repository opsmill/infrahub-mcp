"""CLI entry point for the infrahub-mcp server."""

import argparse

from infrahub_mcp.server import mcp


def main() -> None:
    """Entry point for the infrahub-mcp CLI command."""
    parser = argparse.ArgumentParser(description="Infrahub MCP Server")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "streamable-http", "sse"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()

    mcp.run(transport=args.transport, host=args.host, port=args.port)
