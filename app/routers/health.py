"""Health check endpoints for Render and monitoring."""

import os
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Response, status

from app.config import get_settings
from app.db.mongodb import get_platform_db
from app.db.redis import get_redis
from app.services.model_manager import ModelManager

logger = structlog.get_logger()

router = APIRouter()
settings = get_settings()


@router.get("")
async def health_check(response: Response):
    """Basic liveness check - returns 200 if the service is running.

    This endpoint is used by Render's liveness probe.
    Returns minimal data for quick response.
    """
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.version,
        "timestamp": datetime.now(UTC).isoformat(),
    }


@router.get("/ready")
async def readiness_check(response: Response):
    """Readiness probe - checks all dependencies are initialized.

    Returns 200 only when:
    - MongoDB connection is established
    - Model is loaded and ready

    This is used by Render to determine if the instance should receive traffic.
    """
    pid = os.getpid()

    checks = {
        "mongodb": False,
        "redis": False,
        "model": False,
    }

    # Check MongoDB
    try:
        db = get_platform_db()
        await db.command("ping")
        checks["mongodb"] = True
    except Exception as e:
        logger.debug("mongodb_ping_failed", worker_pid=pid, error=str(e))

    # Check Redis (non-critical, but nice to have)
    try:
        redis = get_redis()
        if redis:
            await redis.ping()
            checks["redis"] = True
    except Exception as e:
        logger.debug("redis_ping_failed", worker_pid=pid, error=str(e))
        # Redis is not critical for readiness

    # Check Model - this is critical
    checks["model"] = ModelManager.is_ready()
    if not checks["model"]:
        logger.debug("model_not_ready", worker_pid=pid, model_info=ModelManager.get_model_info())

    # Determine overall status
    # Model and MongoDB are required, Redis is optional
    critical_checks = checks["mongodb"] and checks["model"]

    if critical_checks:
        return {
            "status": "ready",
            "checks": checks,
            "worker_pid": pid,
            "model_info": ModelManager.get_model_info(),
            "timestamp": datetime.now(UTC).isoformat(),
        }
    else:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {
            "status": "not_ready",
            "checks": checks,
            "worker_pid": pid,
            "timestamp": datetime.now(UTC).isoformat(),
        }


@router.get("/status")
async def detailed_status():
    """Detailed status endpoint for diagnostics and monitoring."""
    pid = os.getpid()

    # Get model info
    model_info = ModelManager.get_model_info()

    # Get database stats
    db_stats = {}
    try:
        _ = get_platform_db()
        db_stats["platform_db_connected"] = True
        db_stats["platform_db_name"] = settings.get_platform_db_name()
    except Exception as e:
        db_stats["platform_db_connected"] = False
        db_stats["error"] = str(e)

    # Get Redis stats
    redis_stats = {}
    try:
        redis = get_redis()
        if redis:
            redis_stats["connected"] = True
            # Try to get memory info
            info = await redis.info("memory")
            redis_stats["used_memory_mb"] = round(info.get("used_memory", 0) / 1024 / 1024, 2)
        else:
            redis_stats["connected"] = False
            redis_stats["reason"] = "not_configured"
    except Exception as e:
        redis_stats["connected"] = False
        redis_stats["error"] = str(e)

    return {
        "service": settings.app_name,
        "version": settings.version,
        "worker_pid": pid,
        "environment": {
            "debug": settings.debug,
            "device_setting": settings.device,
            "base_model": settings.base_model,
            "use_fine_tuned": settings.use_fine_tuned,
        },
        "model": model_info,
        "database": db_stats,
        "cache": redis_stats,
        "timestamp": datetime.now(UTC).isoformat(),
    }
