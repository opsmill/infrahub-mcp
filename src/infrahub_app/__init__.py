"""Infrahub FastMCPApp — generic, schema-agnostic visualization tools."""

# Import modules to trigger @app.ui() and @app.tool() registration
import infrahub_app.explore  # noqa: F401
import infrahub_app.overview  # noqa: F401
from infrahub_app.app import app

__all__ = ["app"]
