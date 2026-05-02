"""Single health endpoint providing liveness and readiness info."""

import os
from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.db.mongodb import get_platform_db
from app.db.redis import get_redis
from app.models.common import ErrorResponse
from app.services.tiny_analyzer import TinyAccountingAnalyzer

logger = structlog.get_logger()

router = APIRouter()


class HealthResponse(BaseModel):
    status: str = Field(..., description="ready or not_ready")
    checks: dict = Field(..., description="Subsystem checks: mongodb, redis, model")
    worker_pid: int = Field(..., alias="workerPid", description="PID of worker process")
    model_info: dict = Field(..., alias="modelInfo", description="Model readiness info")
    service: str = Field(...)
    version: str = Field(...)
    timestamp: str = Field(..., description="ISO timestamp")

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "status": "ready",
                "checks": {"mongodb": True, "redis": True, "model": True},
                "workerPid": 12345,
                "modelInfo": {
                    "name": "tiny_tensorflow_analyzer",
                    "ready": True,
                    "usingTensorflow": True,
                    "modelPath": True,
                },
                "service": "accountia",
                "version": "0.1.0",
                "timestamp": "2024-05-01T12:00:00+00:00",
            }
        },
    }


settings = get_settings()


@router.get(
    "",
    response_model=HealthResponse,
    response_description="Service liveness and readiness",
    summary="Liveness and readiness checks",
    description=(
        "Returns a combined liveness and readiness report including subsystem checks (MongoDB, Redis, model), "
        "worker PID, service/version info and a timestamp. When critical subsystems (MongoDB + model) are not ready, "
        "this endpoint returns HTTP 503."
    ),
    responses={
        200: {"model": HealthResponse, "description": "Service is ready"},
        503: {"model": ErrorResponse, "description": "Service not ready - critical dependencies failing"},
    },
)
async def health(response: Response):
    """Combined health endpoint.

    Returns both liveness and readiness checks in a single response.
    """
    pid = os.getpid()

    checks = {"mongodb": False, "redis": False, "model": False}

    # MongoDB
    try:
        db = get_platform_db()
        await db.command("ping")
        checks["mongodb"] = True
    except Exception as e:
        logger.debug("mongodb_ping_failed", worker_pid=pid, error=str(e))

    # Redis (optional)
    try:
        redis = get_redis()
        if redis:
            await redis.ping()
            checks["redis"] = True
    except Exception as e:
        logger.debug("redis_ping_failed", worker_pid=pid, error=str(e))

    # Model readiness via tiny analyzer
    try:
        checks["model"] = TinyAccountingAnalyzer.is_ready()
    except Exception as e:
        logger.debug("model_check_failed", worker_pid=pid, error=str(e))

    critical = checks["mongodb"] and checks["model"]

    payload = {
        "status": "ready" if critical else "not_ready",
        "checks": checks,
        "workerPid": pid,
        "modelInfo": TinyAccountingAnalyzer.get_model_info(),
        "service": settings.app_name,
        "version": settings.version,
        "timestamp": datetime.now(UTC).isoformat(),
    }

    if not critical:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    # Validate and return using the Pydantic model, emitting camelCase aliases
    validated = HealthResponse.model_validate(payload)
    return validated.model_dump(by_alias=True)
