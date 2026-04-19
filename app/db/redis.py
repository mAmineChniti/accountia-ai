"""Redis client for caching and task queue."""

import json
from typing import Any, Optional

import redis.asyncio as redis
import structlog

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

# Redis client instance
_redis_client: Optional[redis.Redis] = None


async def init_redis() -> None:
    """Initialize Redis connection."""
    global _redis_client
    
    try:
        _redis_client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
        )
        await _redis_client.ping()
        logger.info("redis_connected", url=settings.redis_url)
    except Exception as e:
        logger.warning("redis_connection_failed", error=str(e), fallback="no_caching")
        _redis_client = None


async def close_redis() -> None:
    """Close Redis connection."""
    global _redis_client
    if _redis_client:
        await _redis_client.close()
        _redis_client = None
        logger.info("redis_closed")


def get_redis() -> Optional[redis.Redis]:
    """Get Redis client instance."""
    return _redis_client


async def cache_get(key: str) -> Optional[Any]:
    """Get value from cache."""
    if not _redis_client:
        return None
    
    try:
        value = await _redis_client.get(key)
        if value:
            return json.loads(value)
    except Exception as e:
        logger.debug("cache_get_error", key=key, error=str(e))
    
    return None


async def cache_set(key: str, value: Any, expire: int = 3600) -> bool:
    """Set value in cache with expiration (seconds)."""
    if not _redis_client:
        return False
    
    try:
        await _redis_client.setex(key, expire, json.dumps(value))
        return True
    except Exception as e:
        logger.debug("cache_set_error", key=key, error=str(e))
        return False


async def cache_delete(key: str) -> bool:
    """Delete key from cache."""
    if not _redis_client:
        return False
    
    try:
        await _redis_client.delete(key)
        return True
    except Exception as e:
        logger.debug("cache_delete_error", key=key, error=str(e))
        return False


async def cache_clear_pattern(pattern: str) -> int:
    """Clear all keys matching pattern."""
    if not _redis_client:
        return 0
    
    try:
        keys = await _redis_client.keys(pattern)
        if keys:
            return await _redis_client.delete(*keys)
    except Exception as e:
        logger.debug("cache_clear_error", pattern=pattern, error=str(e))
    
    return 0
