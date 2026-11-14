"""Company-scoped task catalog, schedules and execution history."""
import json
from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from .. import platforms, services
from ..auth import Ctx, get_ctx
from ..db import get_session, utcnow
from ..models import Company, SocialAccount, Task, TaskRun
from ..task_schedules import following, local_instant

router = APIRouter(prefix="/api/tasks", tags=["tasks"])
CATALOG = [
    {"id": "post", "name": "Подготовка поста", "description": "Материал на согласование, публикация в выбранное время", "requires": []},
    {"id": "market", "name": "Анализ рынка", "description": "Актуальные сведения о рынке и конкурентах со ссылками", "requires": ["web_search"]},
    {"id": "recommendations", "name": "Рекомендации по контенту", "description": "Темы и форматы с учётом компании и прошлых публикаций", "requires": []},
    {"id": "statistics", "name": "Сбор статистики сообщества", "description": "Подписчики, просмотры, реакции и вовлечённость Telegram-канала", "requires": ["telegram"]},
]


class TaskIn(BaseModel):
    kind: Literal["post", "market", "recommendations", "statistics"] = "post"
    prompt: str = Field(default="", max_length=2000)
    schedule_kind: Literal["legacy", "interval", "daily", "weekly", "once"] = "legacy"
    interval_minutes: int = Field(default=1440, ge=60, le=525600)
    timezone: str = "UTC"
    local_time: str = Field(default="09:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    weekdays: list[int] = Field(default_factory=list)
    first_run: datetime | None = None
    first_run_local: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
    channel_id: int | None = None
    platform: str | None = None  # пусто = площадка выбирается среди подключённых

    @model_validator(mode="after")
    def validate_schedule(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Неизвестный часовой пояс")
        if any(d not in range(7) for d in self.weekdays):
            raise ValueError("Дни недели должны быть от 0 до 6")
        if self.schedule_kind == "weekly" and not self.weekdays:
            raise ValueError("Выберите дни недели")
        if self.first_run_local:
            if self.first_run is not None:
                raise ValueError("Укажите только одно поле первого запуска")
            local = datetime.fromisoformat(self.first_run_local)
            self.first_run = local_instant(local.date(), local.strftime("%H:%M"), self.timezone).replace(tzinfo=timezone.utc)
        if self.schedule_kind in ("interval", "once") and self.first_run is None:
            raise ValueError("Укажите первое время выполнения с часовым поясом")
        if self.first_run is not None:
            if self.first_run.tzinfo is None:
                raise ValueError("Дата должна содержать часовой пояс")
            self.first_run = self.first_run.astimezone(timezone.utc).replace(tzinfo=None)
            if self.first_run <= utcnow():
                raise ValueError("Укажите будущее время")
        if self.kind == "statistics" and self.channel_id is None:
            raise ValueError("Выберите Telegram-канал")
        if self.schedule_kind == "legacy" and not self.prompt.strip():
            raise ValueError("Опишите задачу")
        return self


class TaskToggle(BaseModel):
    active: bool


def task_out(t: Task) -> dict:
    return {k: getattr(t, k) for k in (
        "id", "kind", "prompt", "interval_minutes", "active", "last_run", "schedule_kind",
        "timezone", "local_time", "weekdays", "next_run", "channel_id", "platform",
    )}


async def tasks_out(session: AsyncSession, tasks) -> list[dict]:
    if not tasks:
        return []
    latest = {}
    runs = (await session.execute(select(TaskRun).where(TaskRun.id.in_(select(func.max(TaskRun.id)).where(TaskRun.task_id.in_([t.id for t in tasks])).group_by(TaskRun.task_id))))).scalars()
    for run in runs:
        if run.task_id not in latest:
            latest[run.task_id] = {"status": run.status, "result": run.result[:180], "error": run.error}
    return [{**task_out(t), "last_result": latest.get(t.id)} for t in tasks]


async def task_for(session: AsyncSession, ctx: Ctx, task_id: int, *, include_deleted=False) -> Task:
    task = await session.get(Task, task_id)
    if task is None or (task.deleted and not include_deleted) or (not ctx.is_admin and task.company_id != ctx.require_company()):
        raise HTTPException(404, "Задача не найдена")
    return task


@router.get("/catalog")
async def catalog(ctx: Ctx = Depends(get_ctx)):
    return CATALOG


@router.get("")
async def list_tasks(ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Task).where(Task.company_id == ctx.require_company(), Task.deleted.is_(False), Task.manual.is_(False)).order_by(Task.id.desc()))).scalars().all()
    return await tasks_out(session, rows)


@router.post("")
async def create_task(body: TaskIn, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    ctx.require_creator()
    cid = ctx.require_company()
    if await session.get(Company, cid) is None:
        raise HTTPException(404, "Компания не найдена")
    if body.channel_id is not None:
        channel = await session.get(SocialAccount, body.channel_id)
        if channel is None or channel.company_id != cid or not channel.active or channel.platform != "telegram":
            raise HTTPException(422, "Выберите активный Telegram-канал компании")
    if body.platform:
        if body.platform not in platforms.REGISTRY:
            raise HTTPException(422, f"Неизвестная площадка: {body.platform}")
        account = (await session.execute(select(SocialAccount).where(
            SocialAccount.company_id == cid, SocialAccount.platform == body.platform,
            SocialAccount.active.is_(True), SocialAccount.analytics_only.is_(False)))).scalars().first()
        if account is None:
            raise HTTPException(422, "Площадка не подключена: добавьте канал в «Каналах»")
    task = Task(company_id=cid, kind=body.kind, prompt=body.prompt.strip(),
                schedule_kind=body.schedule_kind, interval_minutes=body.interval_minutes,
                timezone=body.timezone, local_time=body.local_time,
                weekdays=",".join(str(d) for d in sorted(set(body.weekdays))),
                channel_id=body.channel_id, platform=body.platform or "", created_by=ctx.user.id)
    task.next_run = body.first_run if body.schedule_kind in ("interval", "once") else (
        following(task, utcnow()) if body.schedule_kind != "legacy" else None
    )
    session.add(task)
    await session.commit()
    await services.audit(session, cid, ctx.user.id, "task.created", f"task={task.id} kind={task.kind}")
    return {"id": task.id}


@router.get("/{task_id}")
async def get_task(task_id: int, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    return task_out(await task_for(session, ctx, task_id))


@router.patch("/{task_id}")
async def toggle_task(task_id: int, body: TaskToggle, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    task = await task_for(session, ctx, task_id)
    if task.kind == "report" and task.schedule_kind == "weekly" and not ctx.can_approve:
        raise HTTPException(403, "Расписание отчётов меняет администратор компании")
    task.active = body.active
    await session.commit()
    await services.audit(session, task.company_id, ctx.user.id, "task.toggled", f"task={task.id} active={body.active}")
    return {"ok": True}


@router.delete("/{task_id}")
async def delete_task(task_id: int, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    task = await task_for(session, ctx, task_id)
    if task.kind == "report" and task.schedule_kind == "weekly" and not ctx.can_approve:
        raise HTTPException(403, "Расписание отчётов меняет администратор компании")
    task.active, task.deleted = False, True
    await session.execute(update(TaskRun).where(TaskRun.task_id == task.id, TaskRun.status == "pending").values(status="cancelled", finished_at=utcnow()))
    await session.commit()
    await services.audit(session, task.company_id, ctx.user.id, "task.deleted", f"task={task.id}")
    return {"ok": True}


@router.get("/{task_id}/runs")
async def runs(task_id: int, before: int | None = None, limit: int = Query(20, ge=1, le=100), ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    await task_for(session, ctx, task_id, include_deleted=True)
    q = select(TaskRun).where(TaskRun.task_id == task_id).order_by(TaskRun.id.desc()).limit(limit)
    if before is not None:
        q = q.where(TaskRun.id < before)
    rows = (await session.execute(q)).scalars().all()
    return [{**{k: getattr(r, k) for k in ("id", "scheduled_for", "status", "started_at", "finished_at", "result", "error", "post_id")},
             "sources": json.loads(r.sources), "metrics": json.loads(r.metrics)} for r in rows]
