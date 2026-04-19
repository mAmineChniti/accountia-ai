"""Health check endpoints."""

from fastapi import APIRouter

from app.config import get_settings
from app.db.mongodb import get_platform_db
from app.services.model_manager import ModelManager

router = APIRouter()
settings = get_settings()


@router.get("")
async def health_check():
    """Basic health check."""
    return {"status": "healthy", "service": settings.app_name}


@router.get("/ready")
async def readiness_check():
    """Readiness probe - checks all dependencies."""
    
    checks = {
        "mongodb": False,
        "model": False,
    }
    
    # Check MongoDB
    try:
        db = get_platform_db()
        await db.command("ping")
        checks["mongodb"] = True
    except Exception:
        pass
    
    # Check Model
    checks["model"] = ModelManager.is_ready()
    
    all_ready = all(checks.values())
    
    if all_ready:
        return {
            "status": "ready",
            "checks": checks,
        }
    else:
        return {
            "status": "not_ready",
            "checks": checks,
        }
