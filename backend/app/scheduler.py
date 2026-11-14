"""Планировщик. Всё состояние в БД/Redis, поэтому после перезапуска работа продолжается.

С REDIS_URL тик запускает BullMQ (job scheduler, единый для всех экземпляров); без него — APScheduler в процессе.
"""
import logging
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, update, or_
from sqlalchemy.exc import IntegrityError

from . import jobs, runs, services
from .config import settings
from .db import SessionLocal, utcnow
from .models import Task, TaskRun
from .task_schedules import following, latest_due

log = logging.getLogger(__name__)


async def run_due_tasks() -> int:
    """Persist execution slots before dispatch; recover lost dispatches and expired leases."""
    now, started = utcnow(), 0
    async with SessionLocal() as session:
        task_ids = (await session.execute(select(Task.id).where(Task.active.is_(True), Task.deleted.is_(False)))).scalars().all()
        for task_id in task_ids:
            task = await session.get(Task, task_id, populate_existing=True)
            if task is None or not task.active or task.deleted:
                continue
            previous = task.next_run
            if previous is None:
                if task.schedule_kind != "legacy":
                    continue  # completed one-shot schedule
                previous = task.last_run + timedelta(minutes=task.interval_minutes) if task.last_run else now
            lead = timedelta(hours=24) if task.kind == "post" and task.schedule_kind != "legacy" else timedelta()
            if previous - lead > now:
                continue
            slot = previous
            expired_post = bool(lead and slot <= now)
            if slot <= now:
                slot = latest_due(task, slot, now)
            next_slot = following(task, slot)
            claimed = await session.execute(
                update(Task).where(Task.id == task.id, Task.active.is_(True), Task.deleted.is_(False),
                                   Task.next_run == task.next_run)
                .values(next_run=next_slot, last_run=now), execution_options={"synchronize_session": False},
            )
            if claimed.rowcount != 1:
                await session.rollback()
                continue
            session.add(TaskRun(task_id=task.id, company_id=task.company_id, scheduled_for=slot,
                                status="skipped" if expired_post else "pending",
                                error="Время публикации прошло" if expired_post else "",
                                finished_at=now if expired_post else None))
            try:
                await session.commit()
            except IntegrityError:
                await session.rollback()
                continue
        await session.execute(update(TaskRun).where(
            TaskRun.status == "running", TaskRun.lease_until < now, TaskRun.attempts >= 3,
        ).values(status="failed", error="Превышено число попыток после прерванного выполнения", finished_at=now))
        await session.commit()
        # A DB outbox: pending slots survive enqueue failures and process restarts.
        rows = (await session.execute(select(TaskRun.id).join(Task).where(
            Task.active.is_(True), Task.deleted.is_(False),
            or_(TaskRun.status == "pending", (TaskRun.status == "running") & (TaskRun.lease_until < now)),
            or_(TaskRun.queued_at.is_(None), TaskRun.queued_at < now - timedelta(minutes=5)),
            or_(TaskRun.lease_until.is_(None), TaskRun.lease_until <= now),
        ))).scalars().all()
        for run_id in rows:
            claimed = await session.execute(update(TaskRun).where(
                TaskRun.id == run_id,
                or_(TaskRun.queued_at.is_(None), TaskRun.queued_at < now - timedelta(minutes=5)),
            ).values(queued_at=now))
            await session.commit()
            if claimed.rowcount != 1:
                continue
            await jobs.enqueue("ai-generation", "run_task", {"run_id": run_id}, attempts=3, backoff_ms=30_000)
            started += 1
    return started


async def run_tick() -> None:
    await run_due_tasks()
    await runs.maintain()
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
