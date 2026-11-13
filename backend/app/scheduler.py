"""Планировщик. Всё состояние в БД/Redis, поэтому после перезапуска работа продолжается.

С REDIS_URL тик запускает BullMQ (job scheduler, единый для всех экземпляров); без него — APScheduler в процессе.
"""
import logging
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from . import jobs, services
from .config import settings
from .db import SessionLocal, utcnow
from .models import Task

log = logging.getLogger(__name__)


async def run_due_tasks() -> int:
    """Находит регулярные задачи, которым пора запуститься, и ставит их в очередь ai-generation."""
    now, started = utcnow(), 0
    async with SessionLocal() as session:
        tasks = (await session.execute(select(Task).where(Task.active.is_(True)))).scalars().all()
        for task in tasks:
            if task.last_run and now - task.last_run < timedelta(minutes=task.interval_minutes):
                continue
            task.last_run = now
            await session.commit()  # отмечаем запуск ДО постановки в очередь — защита от дублей
            await jobs.enqueue(
                "ai-generation", "run_task", {"task_id": task.id, "company_id": task.company_id},
                attempts=2, backoff_ms=30_000,
            )
            started += 1
    return started


async def run_tick() -> None:
    await run_due_tasks()
    async with SessionLocal() as session:
        await services.publish_due(session)


async def tick() -> None:
    try:
        await run_tick()
    except Exception:
        log.exception("scheduler tick failed")


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(tick, "interval", seconds=settings.scheduler_interval_sec, max_instances=1, coalesce=True)
    return scheduler
