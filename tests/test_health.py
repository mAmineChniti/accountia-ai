"""Tests for health endpoints."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport

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
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_ready_endpoint(client):
    """Test ready health endpoint - mocks both MongoDB and ModelManager as ready."""
    with (
        patch("app.routers.health.ModelManager") as mock_model,
        patch("app.routers.health.get_platform_db") as mock_db,
    ):
        # Mock ModelManager
        mock_model.is_ready.return_value = True
        mock_model.get_model_info.return_value = {"ready": True, "model": "test"}

        # Mock MongoDB
        mock_db_instance = mock_db.return_value
        mock_db_instance.command = AsyncMock(return_value={"ok": 1})

        response = await client.get("/api/health/ready")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "checks" in data
