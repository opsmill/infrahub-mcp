"""Tests for the health check endpoint."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from starlette.testclient import TestClient


class TestHealthEndpoint:
    """Test /health endpoint behavior with mocked Infrahub client."""

    def test_healthy(self) -> None:
        mock_client = MagicMock()
        mock_client.get_version.return_value = "1.2.3"

        with patch("infrahub_mcp.server.InfrahubClient", return_value=mock_client):
            from infrahub_mcp.server import mcp

            app = mcp.http_app()
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert "infrahub_version" not in data

    def test_unhealthy(self) -> None:
        mock_client = MagicMock()
        mock_client.get_version.side_effect = ConnectionError("Connection refused")

        with patch("infrahub_mcp.server.InfrahubClient", return_value=mock_client):
            from infrahub_mcp.server import mcp

            app = mcp.http_app()
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "unhealthy"
