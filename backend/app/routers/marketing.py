"""Authenticated marketing workspace. Employees never gain access to admin settings."""
import json
from datetime import datetime
from typing import Literal
from urllib.parse import urlparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import cache, marketing, services
from ..auth import Ctx, get_ctx
from ..config import settings
from ..db import get_session, utcnow
from ..models import (Company, Competitor, MarketingPlanItem, MarketingDocument, MarketingHypothesis,
                      MarketingSettings, SocialAccount, Task, TaskRun)
from ..task_schedules import following

router = APIRouter(prefix="/api/marketing", tags=["marketing"])


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


async def company(ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    cid = ctx.require_company()
    if await session.get(Company, cid) is None:
        raise HTTPException(404, "Компания не найдена")
    return ctx


def manager(ctx):
    if not ctx.can_approve:
        raise HTTPException(403, "Настройки и согласование доступны администратору компании")


async def owned(session, model, item_id, cid):
    item = await session.get(model, item_id)
    if item is None or item.company_id != cid:
        raise HTTPException(404, "Объект не найден")
    return item


def output(item, fields):
    return {k: getattr(item, k) for k in fields.split()}


def document_out(d):
    return {**output(d, "id run_id kind approved_at created_at"), "data": json.loads(d.data),
            "sources": json.loads(d.sources), "metrics": {k: v for k, v in json.loads(d.metrics).items() if k != "posts" and k != "messages"}}


@router.get("/state")
async def state(days: int = Query(30, ge=7, le=90), channel: str = Query("", max_length=200),
                ctx: Ctx = Depends(company), session: AsyncSession = Depends(get_session)):
    if days not in (7, 30, 90):
        raise HTTPException(422, "Выберите период 7, 30 или 90 дней")
    cid = ctx.require_company()
    profile = await session.get(MarketingSettings, cid)
    competitors = (await session.execute(select(Competitor).where(Competitor.company_id == cid).order_by(Competitor.id))).scalars().all()
    documents = (await session.execute(select(MarketingDocument).where(MarketingDocument.company_id == cid).order_by(MarketingDocument.id.desc()).limit(50))).scalars().all()
    hypotheses = (await session.execute(select(MarketingHypothesis).where(MarketingHypothesis.company_id == cid).order_by(MarketingHypothesis.id.desc()).limit(200))).scalars().all()
    plan = (await session.execute(select(MarketingPlanItem).where(MarketingPlanItem.company_id == cid).order_by(MarketingPlanItem.id.desc()).limit(100))).scalars().all()
    runs = (await session.execute(select(TaskRun, Task.kind).join(Task).where(TaskRun.company_id == cid, Task.kind.in_(marketing.KINDS | {"post"})).order_by(TaskRun.id.desc()).limit(30))).all()
    channels = (await session.execute(select(SocialAccount).where(SocialAccount.company_id == cid, SocialAccount.active.is_(True), SocialAccount.platform == "telegram"))).scalars().all()
    report_task = await session.get(Task, profile.report_task_id) if profile and profile.report_task_id else None
    return {"profile": output(profile, "niche geography goals") if profile else {"niche": "", "geography": "", "goals": ""},
            "permissions": {"write": ctx.can_create, "manage": ctx.can_approve},
            "sources": {"web_search": bool(settings.tavily_api_key), "demo": settings.llm_provider == "stub"},
            "channels": [output(c, "id channel_id") for c in channels],
            "competitors": [output(c, "id name website telegram notes confirmed") for c in competitors],
            "documents": [document_out(d) for d in documents],
            "hypotheses": [output(h, "id document_id title evidence action metric success duration_days status result task_id updated_at") for h in hypotheses],
            "plan": [output(p, "id document_id topic format rubric rationale day task_id") for p in plan],
            "runs": [{**output(r, "id task_id status error post_id started_at finished_at"), "kind": kind} for r, kind in runs],
            "schedule": output(report_task, "id active timezone local_time next_run") if report_task and not report_task.deleted else None,
            "analytics": await marketing.analytics(session, cid, days, channel)}


class ProfileIn(Input):
    niche: str = Field(max_length=500)
    geography: str = Field(max_length=300)
    goals: str = Field(max_length=4000)


@router.put("/profile")
async def profile(body: ProfileIn, ctx: Ctx = Depends(company), session: AsyncSession = Depends(get_session)):
    manager(ctx)
    item = await session.get(MarketingSettings, ctx.company_id)
    if item is None:
        item = MarketingSettings(company_id=ctx.company_id)
        session.add(item)
    for key, value in body.model_dump().items():
        setattr(item, key, value.strip())
    await services.audit(session, ctx.company_id, ctx.user.id, "marketing.profile")
    await cache.invalidate(f"ctx:prompt:{ctx.company_id}")
    return {"ok": True}


class CompetitorIn(Input):
    name: str = Field(min_length=1, max_length=200)
    website: str = Field(default="", max_length=1000)
    telegram: str = Field(default="", max_length=300)
    notes: str = Field(default="", max_length=2000)

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value):
        if not value.strip():
            raise ValueError("Укажите название")
        return value.strip()

    @field_validator("website", "telegram")
    @classmethod
    def safe_link(cls, value):
        if not value:
            return value
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Укажите ссылку http:// или https://")
        return value


@router.post("/competitors")
async def add_competitor(body: CompetitorIn, ctx: Ctx = Depends(company), session: AsyncSession = Depends(get_session)):
    ctx.require_creator()
    count = len((await session.execute(select(Competitor.id).where(Competitor.company_id == ctx.company_id))).scalars().all())
    if count >= 10:
        raise HTTPException(422, "В первом этапе доступно до 10 конкурентов")
    item = Competitor(company_id=ctx.company_id, confirmed=True, **body.model_dump())
    session.add(item)
    await services.audit(session, ctx.company_id, ctx.user.id, "marketing.competitor.added", body.name)
    return {"id": item.id}


@router.post("/competitors/{item_id}/confirm")
async def confirm_competitor(item_id: int, ctx: Ctx = Depends(company), session: AsyncSession = Depends(get_session)):
    ctx.require_creator()
    item = await owned(session, Competitor, item_id, ctx.company_id)
    item.confirmed = True
    await services.audit(session, ctx.company_id, ctx.user.id, "marketing.competitor.confirmed", str(item_id))
    return {"ok": True}


@router.delete("/competitors/{item_id}")
async def delete_competitor(item_id: int, ctx: Ctx = Depends(company), session: AsyncSession = Depends(get_session)):
    ctx.require_creator()
    item = await owned(session, Competitor, item_id, ctx.company_id)
    await session.delete(item)
    await services.audit(session, ctx.company_id, ctx.user.id, "marketing.competitor.deleted", str(item_id))
    return {"ok": True}


class JobIn(Input):
    kind: Literal["research", "competitors", "hypotheses", "strategy", "plan", "report", "sync"]
    prompt: str = Field(default="", max_length=2000)
    days: Literal[7, 30, 90] = 30
    channel: str = Field(default="", max_length=200)
    channel_id: int | None = None


@router.post("/jobs", status_code=202)
async def start_job(body: JobIn, ctx: Ctx = Depends(company), session: AsyncSession = Depends(get_session)):
    ctx.require_creator()
    if body.kind in ("research", "competitors") and not settings.tavily_api_key:
        raise HTTPException(422, "Веб-поиск не подключён. Администратору сервиса нужно настроить TAVILY_API_KEY")
    if body.kind == "sync":
        account = await session.get(SocialAccount, body.channel_id) if body.channel_id else None
        if account is None or account.company_id != ctx.company_id or not account.active or account.platform != "telegram":
            raise HTTPException(422, "Выберите Telegram-канал своей компании")
        from ..telegram_analytics import connection_session
        try:
            await connection_session(session, ctx.company_id)
        except marketing.jobs.PermanentFailure as exc:
            raise HTTPException(422, str(exc))
    try:
        async with cache.lock(f"marketing:start:{ctx.company_id}:{body.kind}", ttl_sec=30):
            pending = await session.scalar(select(TaskRun.id).join(Task).where(TaskRun.company_id == ctx.company_id,
                Task.kind == body.kind, TaskRun.status.in_(["pending", "running"])).limit(1))
            if pending:
                raise HTTPException(409, "Такой анализ уже выполняется")
            await cache.rate_limit(f"marketing:start:rate:{ctx.company_id}", 10)
            task, run = await marketing.create_run(session, ctx.company_id, ctx.user.id, body.kind,
                body.model_dump(exclude={"kind", "channel_id"}), body.channel_id)
            await services.audit(session, ctx.company_id, ctx.user.id, "marketing.started", f"kind={body.kind} run={run.id}")
            run_id = run.id
    except (cache.LockBusy, cache.RateLimited) as exc:
        raise HTTPException(429, "Слишком много запусков, повторите позже") from exc
    await marketing.dispatch(run_id)
    return {"run_id": run_id}


class HypothesisIn(Input):
    status: Literal["proposed", "running", "confirmed", "rejected", "insufficient", "archived"]
    result: str = Field(default="", max_length=4000)


@router.patch("/hypotheses/{item_id}")
async def update_hypothesis(item_id: int, body: HypothesisIn, ctx: Ctx = Depends(company), session: AsyncSession = Depends(get_session)):
    ctx.require_creator()
    item = await owned(session, MarketingHypothesis, item_id, ctx.company_id)
    if body.status in ("confirmed", "rejected") and not body.result.strip():
        raise HTTPException(422, "Запишите фактический результат эксперимента")
    item.status, item.result, item.updated_at = body.status, body.result.strip(), utcnow()
    await services.audit(session, ctx.company_id, ctx.user.id, "marketing.hypothesis.updated", str(item_id))
    return {"ok": True}


@router.post("/documents/{item_id}/approve")
async def approve_strategy(item_id: int, ctx: Ctx = Depends(company), session: AsyncSession = Depends(get_session)):
    manager(ctx)
    item = await owned(session, MarketingDocument, item_id, ctx.company_id)
    if item.kind != "strategy":
        raise HTTPException(422, "Согласование доступно для стратегии")
    item.approved_by, item.approved_at = ctx.user.id, utcnow()
    await services.audit(session, ctx.company_id, ctx.user.id, "marketing.strategy.approved", str(item_id))
    await cache.invalidate(f"ctx:prompt:{ctx.company_id}")
    return {"ok": True}


@router.post("/plan/{item_id}/prepare", status_code=202)
async def prepare_plan(item_id: int, ctx: Ctx = Depends(company), session: AsyncSession = Depends(get_session)):
    ctx.require_creator()
    item = await owned(session, MarketingPlanItem, item_id, ctx.company_id)
    if item.task_id:
        raise HTTPException(409, "Материал уже передан в подготовку")
    prompt = f"Подготовь пост. Тема: {item.topic}. Формат: {item.format}. Рубрика: {item.rubric}. {item.rationale}"
    task, run = await marketing.create_run(session, ctx.company_id, ctx.user.id, "post", {})
    task.prompt = prompt
    # Claim atomically: two clicks must not generate two materials.
    claimed = await session.execute(update(MarketingPlanItem).where(MarketingPlanItem.id == item.id,
        MarketingPlanItem.company_id == ctx.company_id, MarketingPlanItem.task_id.is_(None)).values(task_id=task.id))
    if claimed.rowcount != 1:
        await session.rollback()
        raise HTTPException(409, "Материал уже передан в подготовку")
    await services.audit(session, ctx.company_id, ctx.user.id, "marketing.plan.prepared", str(item_id))
    await marketing.dispatch(run.id)
    return {"run_id": run.id}


@router.post("/hypotheses/{item_id}/prepare", status_code=202)
async def prepare_hypothesis(item_id: int, ctx: Ctx = Depends(company), session: AsyncSession = Depends(get_session)):
    ctx.require_creator()
    item = await owned(session, MarketingHypothesis, item_id, ctx.company_id)
    if item.task_id:
        raise HTTPException(409, "Пост для гипотезы уже передан в подготовку")
    task, run = await marketing.create_run(session, ctx.company_id, ctx.user.id, "post", {})
    task.prompt = f"Подготовь пост для эксперимента: {item.title}. {item.action}. Основание: {item.evidence}. Не выдумывай факты."
    claimed = await session.execute(update(MarketingHypothesis).where(MarketingHypothesis.id == item.id,
        MarketingHypothesis.company_id == ctx.company_id, MarketingHypothesis.task_id.is_(None)).values(task_id=task.id))
    if claimed.rowcount != 1:
        await session.rollback()
        raise HTTPException(409, "Пост для гипотезы уже передан в подготовку")
    await services.audit(session, ctx.company_id, ctx.user.id, "marketing.hypothesis.prepared", str(item_id))
    await marketing.dispatch(run.id)
    return {"run_id": run.id}


class ScheduleIn(Input):
    active: bool
    timezone: str = Field(max_length=80)
    local_time: str = Field(default="09:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, ZoneInfoNotFoundError):
            raise ValueError("Неизвестный часовой пояс")
        return value


@router.put("/report-schedule")
async def schedule(body: ScheduleIn, ctx: Ctx = Depends(company), session: AsyncSession = Depends(get_session)):
    manager(ctx)
    try:
        async with cache.lock(f"marketing:schedule:{ctx.company_id}", ttl_sec=30):
            profile = await session.get(MarketingSettings, ctx.company_id)
            if profile is None:
                profile = MarketingSettings(company_id=ctx.company_id)
                session.add(profile)
            task = await session.get(Task, profile.report_task_id) if profile.report_task_id else None
            if task is None:
                task = Task(company_id=ctx.company_id, kind="report", prompt=marketing.dump({"days": 7}),
                            created_by=ctx.user.id, schedule_kind="weekly", weekdays="0")
                session.add(task)
                await session.flush()
                profile.report_task_id = task.id
            task.active, task.deleted = body.active, False
            task.timezone, task.local_time = body.timezone, body.local_time
            task.next_run = following(task, utcnow())
            await services.audit(session, ctx.company_id, ctx.user.id, "marketing.report.schedule", marketing.dump(body.model_dump()))
    except cache.LockBusy:
        raise HTTPException(409, "Расписание уже изменяется")
    return {"ok": True}
