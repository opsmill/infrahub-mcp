"""Tests for the infrahub_app package skeleton."""

from __future__ import annotations

from fastmcp.apps import FastMCPApp


def test_app_is_fastmcp_app() -> None:
    from infrahub_app import app

    assert isinstance(app, FastMCPApp)
    assert app.name == "Infrahub"
