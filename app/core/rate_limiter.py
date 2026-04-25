"""Rate limiting middleware for FastAPI.

Provides Redis-backed rate limiting with configurable limits per endpoint.
"""

from collections.abc import Callable

import structlog
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config import get_settings
from app.db.redis import rate_limit_check

logger = structlog.get_logger()
settings = get_settings()


class RateLimiter(BaseHTTPMiddleware):
    """Rate limiting middleware with Redis backend.

    Rate limits are applied per API key (X-API-Key header).
    Falls back to IP address if no API key provided.

    Default limits:
    - 100 requests per minute for general endpoints
    - 10 requests per minute for expensive endpoints (LLM, accounting jobs)
    """

    # Endpoint-specific limits (path pattern -> (max_requests, window_seconds))
    ENDPOINT_LIMITS: dict[str, tuple[int, int]] = {
        # Expensive endpoints - stricter limits
        "/api/accounting/jobs": (10, 60),  # 10 jobs per minute
        "/api/accounting/business/": (20, 60),  # 20 history requests per minute
        # General endpoints
        "/api/health": (100, 60),  # Health checks are cheap
    }

    # Default limits for unmatched endpoints
    DEFAULT_LIMIT = (60, 60)  # 60 requests per minute

    def __init__(
        self,
        app: ASGIApp,
        default_max_requests: int = 60,
        default_window_seconds: int = 60,
        exclude_paths: list[str] | None = None,
    ):
        super().__init__(app)
        self.default_max_requests = default_max_requests
        self.default_window_seconds = default_window_seconds
        self.exclude_paths = exclude_paths or ["/docs", "/redoc", "/openapi.json", "/api/health"]

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Skip rate limiting for excluded paths
        path = request.url.path
        for exclude in self.exclude_paths:
            if path.startswith(exclude):
                return await call_next(request)

        # Get client identifier (API key preferred, fallback to IP)
        client_id = self._get_client_id(request)

        # Determine rate limit for this endpoint
        max_requests, window_seconds = self._get_limit_for_path(path)

        # Check rate limit
        rate_key = f"rl:{client_id}:{path.split('/')[3] if len(path.split('/')) > 3 else 'default'}"

        is_allowed, remaining, reset_in = await rate_limit_check(rate_key, max_requests, window_seconds)

        # Add rate limit headers
        response = await call_next(request)

        response.headers["X-RateLimit-Limit"] = str(max_requests)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_in)

        if not is_allowed:
            logger.warning(
                "rate_limit_exceeded",
                client_id=client_id[:20] if client_id else None,
                path=path,
                limit=max_requests,
                window=window_seconds,
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": "Rate limit exceeded",
                    "detail": f"Too many requests. Limit: {max_requests} per {window_seconds}s. Retry in {reset_in}s.",
                    "retry_after": reset_in,
                },
                headers={
                    "Retry-After": str(reset_in),
                    "X-RateLimit-Limit": str(max_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_in),
                },
            )

        return response

    def _get_client_id(self, request: Request) -> str:
        """Get client identifier from request."""
        # Prefer API key for rate limiting
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return f"api:{api_key[:16]}"  # Use first 16 chars for key privacy

        # Fallback to IP address
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            # Use first IP in X-Forwarded-For (client IP behind proxy)
            return f"ip:{forwarded.split(',')[0].strip()}"

        # Last resort: direct connection IP
        client_ip = request.client.host if request.client else "unknown"
        return f"ip:{client_ip}"

    def _get_limit_for_path(self, path: str) -> tuple[int, int]:
        """Get rate limit for a specific path."""
        for pattern, limit in self.ENDPOINT_LIMITS.items():
            if path.startswith(pattern):
                return limit
        return (self.default_max_requests, self.default_window_seconds)


class RateLimitByAPIKey:
    """Dependency for per-endpoint rate limiting.

    Usage in endpoint:
        @router.post("/jobs", dependencies=[Depends(RateLimitByAPIKey(10, 60))])
    """

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds

    async def __call__(self, request: Request) -> None:
        client_id = self._get_client_id(request)
        path = request.url.path

        rate_key = f"rl:{client_id}:{path}"

        is_allowed, remaining, reset_in = await rate_limit_check(rate_key, self.max_requests, self.window_seconds)

        # Store rate limit info in request state for access in response
        request.state.rate_limit_limit = self.max_requests
        request.state.rate_limit_remaining = remaining
        request.state.rate_limit_reset = reset_in

        if not is_allowed:
            from fastapi import HTTPException

            logger.warning(
                "endpoint_rate_limit_exceeded",
                client_id=client_id[:20] if client_id else None,
                path=path,
            )
            raise HTTPException(
                status_code=429,
                detail=(
                    f"Rate limit exceeded. Limit: {self.max_requests} per {self.window_seconds}s. Retry in {reset_in}s."
                ),
                headers={"Retry-After": str(reset_in)},
            )

    def _get_client_id(self, request: Request) -> str:
        """Get client identifier from request."""
        api_key = request.headers.get("X-API-Key")
        if api_key:
            return f"api:{api_key[:16]}"

        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return f"ip:{forwarded.split(',')[0].strip()}"

        client_ip = request.client.host if request.client else "unknown"
        return f"ip:{client_ip}"
