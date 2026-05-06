"""Unit tests for rate limiting middleware and dependency."""

from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from app.core.rate_limiter import RateLimitByAPIKey, RateLimiter


def _build_request(path: str, headers: dict[str, str] | None = None) -> Request:
    raw_headers = []
    if headers:
        raw_headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]

    scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": raw_headers,
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return Request(scope)


def test_get_client_id_prefers_api_key():
    limiter = RateLimiter(app=AsyncMock())
    request = _build_request("/api/accounting/jobs", {"X-API-Key": "1234567890abcdefghijklmnop"})

    client_id = limiter._get_client_id(request)

    assert client_id == "api:1234567890abcdef"


def test_get_client_id_uses_forwarded_for_when_no_api_key():
    limiter = RateLimiter(app=AsyncMock())
    request = _build_request("/api/accounting/jobs", {"X-Forwarded-For": "10.0.0.5, 10.0.0.1"})

    client_id = limiter._get_client_id(request)

    assert client_id == "ip:10.0.0.5"


def test_get_limit_for_path_matches_configured_patterns():
    limiter = RateLimiter(app=AsyncMock(), default_max_requests=77, default_window_seconds=45)

    assert limiter._get_limit_for_path("/api/accounting/jobs") == (10, 60)
    assert limiter._get_limit_for_path("/api/accounting/business/history") == (20, 60)
    assert limiter._get_limit_for_path("/api/unknown") == (77, 45)


@pytest.mark.asyncio
async def test_dispatch_skips_excluded_paths(monkeypatch):
    limiter = RateLimiter(app=AsyncMock(), exclude_paths=["/api/health"])
    request = _build_request("/api/health")
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    rate_limit_mock = AsyncMock()
    monkeypatch.setattr("app.core.rate_limiter.rate_limit_check", rate_limit_mock)

    response = await limiter.dispatch(request, call_next)

    assert response.status_code == 200
    rate_limit_mock.assert_not_awaited()
    call_next.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_allows_and_adds_headers(monkeypatch):
    limiter = RateLimiter(app=AsyncMock(), default_max_requests=60, default_window_seconds=60)
    request = _build_request("/api/accounting/jobs", {"X-API-Key": "api-key"})
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    monkeypatch.setattr(
        "app.core.rate_limiter.rate_limit_check",
        AsyncMock(return_value=(True, 9, 12)),
    )

    response = await limiter.dispatch(request, call_next)

    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == "10"
    assert response.headers["X-RateLimit-Remaining"] == "9"
    assert response.headers["X-RateLimit-Reset"] == "12"


@pytest.mark.asyncio
async def test_dispatch_rejects_when_limit_exceeded(monkeypatch):
    limiter = RateLimiter(app=AsyncMock())
    request = _build_request("/api/accounting/jobs")
    call_next = AsyncMock(return_value=Response("ok", status_code=200))

    monkeypatch.setattr(
        "app.core.rate_limiter.rate_limit_check",
        AsyncMock(return_value=(False, 0, 30)),
    )

    response = await limiter.dispatch(request, call_next)

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "30"
    assert response.headers["X-RateLimit-Remaining"] == "0"


@pytest.mark.asyncio
async def test_rate_limit_dependency_sets_request_state(monkeypatch):
    dependency = RateLimitByAPIKey(max_requests=5, window_seconds=20)
    request = _build_request("/api/accounting/jobs", {"X-API-Key": "abc"})

    monkeypatch.setattr(
        "app.core.rate_limiter.rate_limit_check",
        AsyncMock(return_value=(True, 4, 18)),
    )

    await dependency(request)

    assert request.state.rate_limit_limit == 5
    assert request.state.rate_limit_remaining == 4
    assert request.state.rate_limit_reset == 18


@pytest.mark.asyncio
async def test_rate_limit_dependency_raises_http_exception(monkeypatch):
    dependency = RateLimitByAPIKey(max_requests=1, window_seconds=60)
    request = _build_request("/api/accounting/jobs")

    monkeypatch.setattr(
        "app.core.rate_limiter.rate_limit_check",
        AsyncMock(return_value=(False, 0, 25)),
    )

    with pytest.raises(HTTPException) as exc:
        await dependency(request)

    assert exc.value.status_code == 429
    assert exc.value.headers == {"Retry-After": "25"}
