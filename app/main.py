import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse

from app.config import get_settings
from app.core.rate_limiter import RateLimiter
from app.db.mongodb import close_mongodb, init_mongodb
from app.db.redis import close_redis, init_redis
from app.routers import accounting, health
from app.services.tiny_analyzer import TinyAccountingAnalyzer

logger = structlog.get_logger()
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager with eager model initialization."""
    pid = os.getpid()
    logger.info(
        "starting_service",
        service="Accountia AI Accountant",
        version=settings.version,
        worker_pid=pid,
    )

    # Initialize MongoDB connection
    try:
        await init_mongodb()
        logger.info("mongodb_initialized")
    except Exception as e:
        logger.error("mongodb_init_failed", error=str(e))
        # Continue without MongoDB - some endpoints may fail

    # Initialize Redis (for caching) - non-critical
    try:
        await init_redis()
        logger.info("redis_initialized")
    except Exception as e:
        logger.warning("redis_init_failed", error=str(e), fallback="no_caching")

    # Skip heavy model loading for free tier - use tiny analyzer instead
    logger.info("model_initialization_skipped", reason="using_tiny_analyzer")

    # Initialize tiny analyzer (optional, low RAM - 66M params vs 1.5B)
    try:
        _ready = await TinyAccountingAnalyzer.initialize()
        if _ready:
            logger.info("tiny_analyzer_ready", worker_pid=pid)
        else:
            logger.info("tiny_analyzer_not_ready", reason="model_missing_or_tf_unavailable")
    except Exception as e:
        logger.warning("tiny_analyzer_failed", error=str(e), fallback="rule_based")

    yield

    # Shutdown
    logger.info("shutting_down_service", worker_pid=pid)

    # Clean up model resources
    # No heavy ModelManager in this build; tiny analyzer has no shutdown hook

    # Close database connections
    try:
        await close_mongodb()
    except Exception as e:
        logger.error("mongodb_close_error", error=str(e))

    try:
        await close_redis()
    except Exception as e:
        logger.error("redis_close_error", error=str(e))

    logger.info("service_shutdown_complete", worker_pid=pid)


app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description=(
        "AI-powered accounting service for Tunisian businesses. "
        "Provides automated journal entry generation, tax calculations (VAT, Corporate Tax, Withholding), "
        "financial reports, and AI insights."
    ),
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    openapi_tags=[
        {
            "name": "Accounting",
            "description": "Core accounting operations: create jobs, get results, tax calculations",
        },
        {"name": "System", "description": "Health checks and service info"},
    ],
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.debug else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RequestResponseLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log incoming requests and outgoing responses when enabled.

    - Redacts sensitive headers (`authorization`, `x-api-key`, `cookie`).
    - Truncates bodies to `request_log_max_body_chars` to avoid huge logs.
    - Only active when `settings.enable_request_logging` is True.
    """

    async def dispatch(self, request: StarletteRequest, call_next):
        settings_local = get_settings()
        logger_local = structlog.get_logger()

        if not settings_local.enable_request_logging:
            return await call_next(request)

        # Read and decode request body (may be empty)
        try:
            body_bytes = await request.body()
        except Exception:
            body_bytes = b""

        try:
            body_text = body_bytes.decode(errors="replace")
        except Exception:
            body_text = "<binary>"

        # Redact sensitive headers
        headers = {k.lower(): v for k, v in request.headers.items()}
        for h in ("authorization", "x-api-key", "cookie", "set-cookie"):
            if h in headers:
                headers[h] = "***REDACTED***"

        max_chars = settings_local.request_log_max_body_chars
        logger_local.info(
            "http.request",
            method=request.method,
            url=str(request.url),
            headers=headers,
            body=(body_text[:max_chars] + "..." if len(body_text) > max_chars else body_text),
        )

        # Call next and capture response body
        response = await call_next(request)

        # Consume response body iterator to capture content
        resp_body = b""
        try:
            async for chunk in response.body_iterator:
                resp_body += chunk
        except Exception:
            # If body iterator fails, fallback to empty
            resp_body = b""

        try:
            resp_text = resp_body.decode(errors="replace")
        except Exception:
            resp_text = "<binary>"

        # Redact response headers if any sensitive present
        resp_headers = {k.lower(): v for k, v in response.headers.items()}
        for h in ("set-cookie",):
            if h in resp_headers:
                resp_headers[h] = "***REDACTED***"

        logger_local.info(
            "http.response",
            status_code=response.status_code,
            headers=resp_headers,
            body=(resp_text[:max_chars] + "..." if len(resp_text) > max_chars else resp_text),
        )

        # Recreate response since body_iterator was consumed
        resp_headers = dict(response.headers)
        return StarletteResponse(
            content=resp_body,
            status_code=response.status_code,
            headers=resp_headers,
            media_type=response.media_type,
        )


# Add request/response logging middleware (enabled via settings)
app.add_middleware(RequestResponseLoggingMiddleware)

# Rate Limiting (Redis-backed, with fallback)
app.add_middleware(
    RateLimiter,
    default_max_requests=60,
    default_window_seconds=60,
    exclude_paths=["/docs", "/redoc", "/openapi.json", "/api/health", "/api/health/ready", "/api/health/status"],
)

# Routers
app.include_router(accounting.router, prefix="/api/accounting", tags=["Accounting"])
app.include_router(health.router, prefix="/api/health", tags=["System"])


class ServiceInfoResponse(BaseModel):
    service: str = Field(...)
    version: str = Field(...)
    status: str = Field(...)
    description: str = Field(...)

    model_config = {
        "json_schema_extra": {
            "example": {
                "service": "Accountia AI Accountant",
                "version": settings.version,
                "status": "operational",
                "description": "AI-powered accounting for Tunisian businesses",
            }
        }
    }


@app.get(
    "/",
    tags=["System"],
    summary="Service Info",
    description="Get service health and version information",
    response_model=ServiceInfoResponse,
)
async def root():
    return ServiceInfoResponse(
        service="Accountia AI Accountant",
        version=settings.version,
        status="operational",
        description="AI-powered accounting for Tunisian businesses",
    ).model_dump(by_alias=False)
