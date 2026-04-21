"""Simple Redis-backed job queue for accounting tasks.

This module provides a lightweight enqueue function that pushes a JSON
message to a Redis list. A separate worker script consumes the list and
processes tasks.
"""

import json
from typing import Any

import redis.asyncio as redis
from app.config import get_settings

settings = get_settings()


QUEUE_KEY = "accounting_job_queue"


async def enqueue_job(message: dict[str, Any]) -> None:
    """Push a JSON-serializable message onto the accounting job queue."""
    r = redis.from_url(settings.redis_url, decode_responses=True)
    await r.rpush(QUEUE_KEY, json.dumps(message))


async def dequeue_job(timeout: int = 0) -> dict[str, Any] | None:
    """Pop a job from the queue using BLPOP (blocking). Returns dict or None on timeout."""
    r = redis.from_url(settings.redis_url, decode_responses=True)
    res = await r.blpop(QUEUE_KEY, timeout=timeout)
    if not res:
        return None
    _, payload = res
    return json.loads(payload)
