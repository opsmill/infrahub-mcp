"""Tests for the health check endpoint."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from infrahub_sdk.exceptions import AuthenticationError, ServerNotReachableError, ServerNotResponsiveError
from starlette.testclient import TestClient

from infrahub_mcp.config import ServerConfig
from infrahub_mcp.server import mcp


@pytest.fixture(autouse=True)
def _force_none_auth_mode() -> Generator[None]:
    """Ensure health tests exercise the shared-credential path regardless of env."""
    with patch("infrahub_mcp.server._config", ServerConfig(auth_mode="none")):
        yield


class TestHealthEndpoint:
    """Test /health endpoint behavior with mocked Infrahub client."""

    def test_healthy(self) -> None:
        mock_client = MagicMock()
        mock_client.get_version = AsyncMock(return_value="1.2.3")

        with patch("infrahub_mcp.server.InfrahubClient", return_value=mock_client):
            app = mcp.http_app()
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "healthy"
            assert "infrahub_version" not in data

    def test_unreachable(self) -> None:
        mock_client = MagicMock()
        mock_client.get_version = AsyncMock(side_effect=ServerNotReachableError(address="http://localhost:8000"))

        with (
            patch("infrahub_mcp.server.InfrahubClient", return_value=mock_client),
            patch.dict("os.environ", {"INFRAHUB_ADDRESS": "http://localhost:8000"}),
        ):
            app = mcp.http_app()
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "unhealthy"
            assert "unreachable" in data["reason"]
            assert "http://localhost:8000" in data["reason"]

    def test_unreachable_client_construction_fails(self) -> None:
        """Verify no UnboundLocalError when InfrahubClient() itself raises."""
        with (
            patch(
                "infrahub_mcp.server.InfrahubClient",
                side_effect=ServerNotReachableError(address="http://bad:8000"),
            ),
            patch.dict("os.environ", {"INFRAHUB_ADDRESS": "http://bad:8000"}),
        ):
            app = mcp.http_app()
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "unhealthy"
            assert "unreachable" in data["reason"]

    def test_not_responsive(self) -> None:
        mock_client = MagicMock()
        mock_client.get_version = AsyncMock(
            side_effect=ServerNotResponsiveError(url="http://localhost:8000/api/query/graphql", timeout=10)
        )

        with patch("infrahub_mcp.server.InfrahubClient", return_value=mock_client):
            app = mcp.http_app()
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "unhealthy"
            assert "unable to read" in data["reason"].lower()

    def test_authentication_error(self) -> None:
        mock_client = MagicMock()
        mock_client.get_version = AsyncMock(side_effect=AuthenticationError(message="Invalid token"))

        with patch("infrahub_mcp.server.InfrahubClient", return_value=mock_client):
            app = mcp.http_app()
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "unhealthy"
            assert "invalid token" in data["reason"].lower()

    def test_unhealthy(self) -> None:
        mock_client = MagicMock()
        mock_client.get_version = AsyncMock(side_effect=ConnectionError("Connection refused"))

        with patch("infrahub_mcp.server.InfrahubClient", return_value=mock_client):
            app = mcp.http_app()
            client = TestClient(app)
            response = client.get("/health")
            assert response.status_code == 503
            data = response.json()
            assert data["status"] == "unhealthy"
