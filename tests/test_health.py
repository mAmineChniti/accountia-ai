"""Tests for health endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    """Create async test client."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_root_endpoint(client):
    """Test root endpoint returns service info."""
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "Accountia AI Accountant"
    assert "version" in data
    assert "status" in data


@pytest.mark.asyncio
async def test_health_endpoint(client):
    """Test basic health endpoint."""
    response = await client.get("/api/health")
    assert response.status_code in (200, 503)
    data = response.json()
    assert "status" in data


@pytest.mark.asyncio
async def test_health_ready_endpoint(client):
    """Test ready health endpoint - mocks both MongoDB and ModelManager as ready."""
    with (
        patch("app.routers.health.TinyAccountingAnalyzer") as mock_analyzer,
        patch("app.routers.health.get_platform_db") as mock_db,
    ):
        # Mock tiny analyzer
        mock_analyzer.is_ready.return_value = True
        mock_analyzer.get_model_info.return_value = {"ready": True, "name": "tiny_tensorflow_analyzer"}

        # Mock MongoDB
        mock_db_instance = mock_db.return_value
        mock_db_instance.command = AsyncMock(return_value={"ok": 1})

        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "checks" in data
