"""Redis client for caching, rate limiting, and request deduplication."""

import json
from typing import Any

import redis.asyncio as redis
import structlog

from app.config import get_settings

logger = structlog.get_logger()
settings = get_settings()

# Redis client instance
_redis_client: redis.Redis | None = None


async def init_redis() -> None:
    """Initialize Redis connection."""
    global _redis_client

    try:
        _redis_client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
            max_connections=20,  # Connection pool size
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


def get_redis() -> redis.Redis | None:
    """Get Redis client instance."""
    return _redis_client


# -----------------------------------------------------------------------------
# Basic Caching
# -----------------------------------------------------------------------------


async def cache_get(key: str) -> Any | None:
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


# -----------------------------------------------------------------------------
# Request Deduplication (for expensive operations like LLM calls)
# -----------------------------------------------------------------------------


async def dedup_check(request_key: str, ttl: int = 60) -> tuple[bool, Any | None]:
    """Check if a request is a duplicate and return cached result if available.

    Args:
        request_key: Unique identifier for the request
        ttl: Time-to-live for the in-flight marker (seconds)

    Returns:
        Tuple of (is_duplicate, cached_result)
        - If is_duplicate is True, cached_result contains the result to return
        - If is_duplicate is False, the caller should proceed with the request
    """
    if not _redis_client:
        return False, None

    try:
        # Check if there's already a result cached
        result_key = f"dedup:result:{request_key}"
        cached = await _redis_client.get(result_key)
        if cached:
            logger.debug("dedup_result_found", request_key=request_key)
            return True, json.loads(cached)

        # Check if there's an in-flight request
        lock_key = f"dedup:lock:{request_key}"
        lock_acquired = await _redis_client.set(lock_key, "1", nx=True, ex=ttl)

        if not lock_acquired:
            # Another request is in flight, wait for result
            logger.debug("dedup_waiting_for_inflight", request_key=request_key)
            for _ in range(ttl * 10):  # Wait up to ttl seconds
                await asyncio.sleep(0.1)
                cached = await _redis_client.get(result_key)
                if cached:
                    return True, json.loads(cached)
            # Timeout - treat as not duplicate
            logger.warning("dedup_wait_timeout", request_key=request_key)
            return False, None

        # We acquired the lock, should proceed with the request
        return False, None

    except Exception as e:
        logger.debug("dedup_check_error", request_key=request_key, error=str(e))
        return False, None


async def dedup_store_result(request_key: str, result: Any, ttl: int = 3600) -> bool:
    """Store the result of a deduplicated request.

    Args:
        request_key: Unique identifier for the request
        result: The result to cache
        ttl: Time-to-live for the result (seconds)

    Returns:
        True if stored successfully
    """
    if not _redis_client:
        return False

    try:
        result_key = f"dedup:result:{request_key}"
        lock_key = f"dedup:lock:{request_key}"

        # Store result and release lock
        pipe = _redis_client.pipeline()
        pipe.setex(result_key, ttl, json.dumps(result))
        pipe.delete(lock_key)
        await pipe.execute()

        logger.debug("dedup_result_stored", request_key=request_key)
        return True

    except Exception as e:
        logger.debug("dedup_store_error", request_key=request_key, error=str(e))
        return False


# -----------------------------------------------------------------------------
# Rate Limiting
# -----------------------------------------------------------------------------


async def rate_limit_check(key: str, max_requests: int, window_seconds: int) -> tuple[bool, int, int]:
    """Check if a request is within rate limits.

    Args:
        key: Rate limit bucket key (e.g., "rl:api_key:abc123")
        max_requests: Maximum allowed requests in the window
        window_seconds: Time window in seconds

    Returns:
        Tuple of (is_allowed, remaining, reset_in_seconds)
    """
    if not _redis_client:
        # If Redis is unavailable, allow the request (fail open)
        return True, max_requests, 0

    try:
        pipe = _redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds, nx=True)  # Only set expiry if new key
        results = await pipe.execute()

        current_count = results[0]

        if current_count > max_requests:
            # Get TTL for accurate reset time
            ttl = await _redis_client.ttl(key)
            return False, 0, max(0, ttl)

        remaining = max(0, max_requests - current_count)
        ttl = await _redis_client.ttl(key)

        return True, remaining, max(0, ttl)

    except Exception as e:
        logger.debug("rate_limit_check_error", key=key, error=str(e))
        # Fail open if Redis error
        return True, max_requests, 0


async def rate_limit_reset(key: str) -> bool:
    """Reset rate limit counter for a key."""
    if not _redis_client:
        return False

    try:
        await _redis_client.delete(key)
        return True
    except Exception as e:
        logger.debug("rate_limit_reset_error", key=key, error=str(e))
        return False


# Import asyncio at the end to avoid circular imports
import asyncio  # noqa: E402
