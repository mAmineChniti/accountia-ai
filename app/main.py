import os
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.core.rate_limiter import RateLimiter
from app.db.mongodb import close_mongodb, init_mongodb
from app.db.redis import close_redis, init_redis
from app.routers import accounting, health
from app.services.model_manager import ModelManager

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

    # Initialize model - EAGER (not background) for proper readiness
    # In multi-worker setup, each worker loads its own model
    logger.info("model_initialization_starting", worker_pid=pid)
    model_initialized = await ModelManager.initialize()

    if model_initialized:
        logger.info(
            "service_started_successfully",
            worker_pid=pid,
            model_ready=True,
        )
    else:
        logger.warning(
            "service_started_with_model_failure",
            worker_pid=pid,
            model_ready=False,
            error=ModelManager.get_error(),
            fallback="groq_api",
        )

    yield

    # Shutdown
    logger.info("shutting_down_service", worker_pid=pid)

    # Clean up model resources
    try:
        await ModelManager.shutdown()
    except Exception as e:
        logger.error("model_shutdown_error", error=str(e))

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


@app.get(
    "/",
    tags=["System"],
    summary="Service Info",
    description="Get service health and version information",
)
async def root():
    return {
        "service": "Accountia AI Accountant",
        "version": settings.version,
        "status": "operational",
        "description": "AI-powered accounting for Tunisian businesses",
    }
