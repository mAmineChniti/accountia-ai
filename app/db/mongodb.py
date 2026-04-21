"""MongoDB connection manager for multi-tenant accounting."""

from typing import Optional

import asyncio
import structlog
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

from bson import Decimal128, ObjectId
from decimal import Decimal as PyDecimal

# Global client instance
_client: Optional[AsyncIOMotorClient] = None
_platform_db: Optional[AsyncIOMotorDatabase] = None


async def init_mongodb() -> None:
    """Initialize MongoDB connection with retry/backoff and clearer logging.

    This helps when using cloud-hosted clusters (mongodb+srv) which may
    require DNS resolution / TLS negotiation and occasionally take longer
    than short timeouts allow.
    """
    global _client, _platform_db

    max_attempts = 5
    attempt = 0
    last_exc: Optional[Exception] = None

    while attempt < max_attempts:
        attempt += 1
        try:
            # Increase server selection timeout for initial connection to cloud DBs
            _client = AsyncIOMotorClient(
                settings.mongo_uri,
                maxPoolSize=50,
                minPoolSize=10,
                serverSelectionTimeoutMS=20000,
            )

            # Verify connection
            await _client.admin.command("ping")

            platform_db_name = settings.get_platform_db_name()
            _platform_db = _client[platform_db_name]

            # Initialize Beanie document models
            from app.db.schemas import AccountingTask, AccountingPeriod

            await init_beanie(
                database=_platform_db,
                document_models=[AccountingTask, AccountingPeriod],
            )

            logger.info("mongodb_connected", platform_db=platform_db_name)
            return
        except Exception as e:  # noqa: BLE001 - surface exceptions for retry
            last_exc = e
            logger.error(
                "mongodb_connection_failed_attempt",
                attempt=attempt,
                max_attempts=max_attempts,
                error=str(e),
            )
            # exponential backoff before retrying
            await asyncio.sleep(min(2 ** attempt, 30))

    logger.error(
        "mongodb_connection_failed_final",
        attempts=attempt,
        error=str(last_exc),
    )
    # raise the last exception for upstream handlers
    raise last_exc


async def close_mongodb() -> None:
    """Close MongoDB connection."""
    global _client
    if _client:
        _client.close()
        logger.info("mongodb_disconnected")


def get_platform_db() -> AsyncIOMotorDatabase:
    """Get platform database (users, businesses)."""
    if _platform_db is None:
        raise RuntimeError("MongoDB not initialized")
    return _platform_db


def get_tenant_db(database_name: str) -> AsyncIOMotorDatabase:
    """Get tenant-specific database by name."""
    if _client is None:
        raise RuntimeError("MongoDB not initialized")
    return _client[database_name]


def get_client() -> AsyncIOMotorClient:
    """Get MongoDB client."""
    if _client is None:
        raise RuntimeError("MongoDB not initialized")
    return _client


def sanitize_bson_types(obj):
    """Recursively convert BSON-specific types to native Python types suitable for Pydantic.

    - Decimal128 -> float
    - decimal.Decimal -> float
    - ObjectId -> str
    Leaves datetimes and other primitives untouched.
    """
    if obj is None:
        return None
    # Primitive types
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, PyDecimal):
        try:
            return float(obj)
        except Exception:
            return str(obj)
    if isinstance(obj, Decimal128):
        try:
            return float(obj.to_decimal())
        except Exception:
            return str(obj)
    if isinstance(obj, ObjectId):
        return str(obj)
    # Datetime (keep as-is)
    from datetime import datetime

    if isinstance(obj, datetime):
        return obj
    # Lists
    if isinstance(obj, list):
        return [sanitize_bson_types(v) for v in obj]
    # Dict-like
    if isinstance(obj, dict):
        return {k: sanitize_bson_types(v) for k, v in obj.items()}
    # Fallback: return as-is
    return obj
