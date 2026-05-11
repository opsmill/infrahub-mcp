"""Tests for the infrahub-mcp CLI entry point."""

from __future__ import annotations

import pytest

from infrahub_mcp import _cli


@pytest.fixture
def captured_run_kwargs(monkeypatch: pytest.MonkeyPatch) -> dict:
    captured: dict = {}

    def fake_run(**kwargs: object) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(_cli.mcp, "run", fake_run)
    monkeypatch.setattr(_cli, "get_asgi_middleware", lambda: None)
    return captured


class TestCliTransportKwargs:
    def test_stdio_does_not_forward_host_or_port(
        self, captured_run_kwargs: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("sys.argv", ["infrahub-mcp", "--transport", "stdio"])
        _cli.main()
        assert captured_run_kwargs == {"transport": "stdio"}

    def test_streamable_http_forwards_host_and_port(
        self, captured_run_kwargs: dict, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "sys.argv",
            ["infrahub-mcp", "--transport", "streamable-http", "--host", "192.0.2.10", "--port", "9000"],
        )
        _cli.main()
        assert captured_run_kwargs == {
            "transport": "streamable-http",
            "host": "192.0.2.10",
            "port": 9000,
        }

    def test_streamable_http_includes_middleware_when_available(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict = {}

        def fake_run(**kwargs: object) -> None:
            captured.update(kwargs)

        sentinel = object()
        monkeypatch.setattr(_cli.mcp, "run", fake_run)
        monkeypatch.setattr(_cli, "get_asgi_middleware", lambda: sentinel)
        monkeypatch.setattr("sys.argv", ["infrahub-mcp", "--transport", "streamable-http"])
        _cli.main()
        assert captured["middleware"] is sentinel
