"""Simple async worker to consume accounting jobs from Redis and process them.

Run with: `python -m scripts.worker` from project root (activate venv first).
"""

import asyncio
import json
import logging
import structlog

from app.config import get_settings
from app.db.mongodb import init_mongodb
from app.tasks.queue import dequeue_job
from app.routers.accounting import process_accounting_task
from app.db.schemas import AccountingTask

settings = get_settings()
logger = structlog.get_logger("accountia.worker")


async def handle_message(msg: dict):
    task_id = msg.get("task_id")
    database_name = msg.get("database_name")
    if not task_id or not database_name:
        logger.error("invalid_job_message", msg=msg)
        return

    # Load the task from platform DB using Beanie
    task = await AccountingTask.find_one({"task_id": task_id})
    if not task:
        logger.error("task_not_found_in_platform_db", task_id=task_id)
        return

    await process_accounting_task(task, database_name)


async def main():
    await init_mongodb()
    logger.info("worker_started", queue_key="accounting_job_queue")
    while True:
        try:
            job = await dequeue_job(timeout=0)
            if job:
                await handle_message(job)
            else:
                await asyncio.sleep(1)
        except Exception as e:
            logger.exception("worker_error", error=str(e))
            await asyncio.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
