"""Tests for the infrahub_app package skeleton."""

from __future__ import annotations

from fastmcp.apps import FastMCPApp

from infrahub_app import app


def test_app_is_fastmcp_app() -> None:
    assert isinstance(app, FastMCPApp)
    assert app.name == "Infrahub"
