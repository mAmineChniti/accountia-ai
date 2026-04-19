"""MongoDB connection manager for multi-tenant accounting."""

from typing import Optional

import structlog
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

# Global client instance
_client: Optional[AsyncIOMotorClient] = None
_platform_db: Optional[AsyncIOMotorDatabase] = None


async def init_mongodb() -> None:
    """Initialize MongoDB connection."""
    global _client, _platform_db
    
    try:
        _client = AsyncIOMotorClient(
            settings.mongo_uri,
            maxPoolSize=50,
            minPoolSize=10,
            serverSelectionTimeoutMS=5000,
        )
        
        # Verify connection
        await _client.admin.command("ping")
        
        platform_db_name = settings.get_platform_db_name()
        _platform_db = _client[platform_db_name]
        
        logger.info(
            "mongodb_connected",
            platform_db=platform_db_name,
        )
    except Exception as e:
        logger.error("mongodb_connection_failed", error=str(e))
        raise


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
