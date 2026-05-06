"""Tests for monitoring-related routes: /api/metrics and /api/alerts."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_metrics_endpoint_returns_prometheus_text(client: AsyncClient):
    res = await client.get("/api/metrics")
    assert res.status_code == 200
    assert "text/plain" in (res.headers.get("content-type") or "")
    assert "#" in res.text


@pytest.mark.asyncio
async def test_alerts_webhook_accepts_payload(client: AsyncClient):
    res = await client.post("/api/alerts", json={"alert": "hello"})
    assert res.status_code == 200
    assert res.json() == {"received": True}

