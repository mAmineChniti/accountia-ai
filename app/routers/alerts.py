import structlog
from fastapi import APIRouter

logger = structlog.get_logger()

router = APIRouter()


@router.post("", summary="Alertmanager webhook")
async def receive_alert(payload: dict) -> dict[str, bool]:
    logger.warning("alertmanager_webhook_received", payload=payload)
    return {"received": True}