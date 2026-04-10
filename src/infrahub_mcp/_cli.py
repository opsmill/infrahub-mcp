"""CLI entry point for the infrahub-mcp server."""

from infrahub_mcp.server import mcp


def main() -> None:
    """Entry point for the infrahub-mcp CLI command."""
    mcp.run()
