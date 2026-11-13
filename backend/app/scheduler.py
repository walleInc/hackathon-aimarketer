"""Фоновые задачи. Всё состояние в БД, поэтому после перезапуска работа продолжается."""
import logging
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from . import agent, services
from .config import settings
from .db import SessionLocal, utcnow
from .models import Task

log = logging.getLogger(__name__)


async def run_due_tasks() -> int:
    """Запускает регулярные задачи: агент сам готовит материал и отправляет на согласование."""
    now, started = utcnow(), 0
    async with SessionLocal() as session:
        tasks = (await session.execute(select(Task).where(Task.active.is_(True)))).scalars().all()
        for task in tasks:
            if task.last_run and now - task.last_run < timedelta(minutes=task.interval_minutes):
                continue
            task.last_run = now
            await session.commit()  # отмечаем запуск ДО выполнения — защита от дублей
            try:
                await agent.handle_message(session, task.company_id, None, f"Регулярная задача: {task.prompt}")
                await services.audit(session, task.company_id, None, "task.run", f"task={task.id}")
                started += 1
            except Exception as e:
                log.exception("task %s failed", task.id)
                await services.notify_admins(f"Задача {task.id} (компания {task.company_id}) завершилась ошибкой: {e}")
    return started


async def tick() -> None:
    try:
        await run_due_tasks()
        async with SessionLocal() as session:
            await services.publish_due(session)
    except Exception:
        log.exception("scheduler tick failed")


def create_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()
    scheduler.add_job(tick, "interval", seconds=settings.scheduler_interval_sec, max_instances=1, coalesce=True)
    return scheduler
