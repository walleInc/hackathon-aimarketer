"""Durable, independently retryable daily content-plan generation."""
import asyncio
import uuid
from datetime import timedelta

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import or_, select, update

from . import agent, cache, jobs, limits
from .db import SessionLocal, utcnow
from .config import settings
from .llm import get_llm
from .models import Company, ContentPlan, ContentPlanDay, ContentPlanItem


class GeneratedItem(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=1500)


class GeneratedDay(BaseModel):
    items: list[GeneratedItem]


async def dispatch_days(plan_id: int | None = None):
    """Database outbox: a lost queue dispatch is retried after five minutes."""
    now = utcnow()
    async with SessionLocal() as session:
        await session.execute(update(ContentPlanDay).where(
            ContentPlanDay.status == "running", ContentPlanDay.lease_until < now, ContentPlanDay.attempts >= 3,
        ).values(status="failed", error="Выполнение прервано после трёх попыток"))
        await session.commit()
        query = select(ContentPlanDay.id).where(
            or_(ContentPlanDay.status == "pending", (ContentPlanDay.status == "running") & (ContentPlanDay.lease_until < now)),
            or_(ContentPlanDay.lease_until.is_(None), ContentPlanDay.lease_until <= now),
            or_(ContentPlanDay.queued_at.is_(None), ContentPlanDay.queued_at < now - timedelta(minutes=5)),
        ).order_by(ContentPlanDay.day, ContentPlanDay.id).limit(50)
        if plan_id is not None:
            query = query.where(ContentPlanDay.plan_id == plan_id)
        ids = (await session.execute(query)).scalars().all()
        for day_id in ids:
            claimed = await session.execute(update(ContentPlanDay).where(
                ContentPlanDay.id == day_id,
                or_(ContentPlanDay.queued_at.is_(None), ContentPlanDay.queued_at < now - timedelta(minutes=5)),
            ).values(queued_at=now))
            await session.commit()
            if claimed.rowcount:
                await jobs.enqueue("ai-generation", "content_plan_day", {"day_id": day_id}, attempts=3)


async def generate_day(day_id: int):
    now, token = utcnow(), uuid.uuid4().hex
    async with SessionLocal() as session:
        claim = await session.execute(update(ContentPlanDay).where(
            ContentPlanDay.id == day_id, ContentPlanDay.attempts < 3,
            or_(ContentPlanDay.status == "pending", (ContentPlanDay.status == "running") & (ContentPlanDay.lease_until < now)),
            or_(ContentPlanDay.lease_until.is_(None), ContentPlanDay.lease_until <= now),
        ).values(status="running", lease_token=token, lease_until=now + timedelta(minutes=5), attempts=ContentPlanDay.attempts + 1))
        await session.commit()
        if not claim.rowcount:
            return
        day = await session.get(ContentPlanDay, day_id)
        plan = await session.get(ContentPlan, day.plan_id)
        try:
            async with jobs.org_slot("ai-generation", day.company_id):
                company = await session.get(Company, day.company_id)
                await limits.check_token_budget(session, company)
                await cache.rate_limit(f"ai:org:{company.id}", settings.ai_rate_limit_per_min)
                previous = (await session.execute(select(ContentPlanItem.title).where(
                    ContentPlanItem.plan_id == plan.id, ContentPlanItem.deleted.is_(False),
                ).order_by(ContentPlanItem.id.desc()).limit(50))).scalars().all()
                prompt = (
                    f"КОНТЕНТ_ПЛАН\nДата: {day.day.isoformat()}. Число задач: {plan.posts_per_day}.\n"
                    f"План: {plan.title}. Пожелания: {plan.wishes}.\nУже использованные темы: {list(previous)}.\n"
                    'Верни строго JSON {"items": [{"title": "тема", "description": "задание маркетологу"}]}. '
                    f"Ровно {plan.posts_per_day} разных задач для постов на указанную дату. "
                    "Описание каждой — 1–2 коротких предложения до 300 символов: содержание, формат и цель. "
                    "Учитывай базу знаний и бренд, не выдумывай факты. Не создавай сами посты и расписания. Пиши по-русски."
                )
                async with asyncio.timeout(180):
                    result = await get_llm().complete(await agent._system_prompt(session, company.id, json_mode=False),
                                                       [{"role": "user", "content": prompt}], json_mode=True)
                await agent._record_llm(session, company.id, result)
                parsed = GeneratedDay.model_validate(agent._parse(result.text))
                if len(parsed.items) != plan.posts_per_day or any(not i.title.strip() or not i.description.strip() for i in parsed.items):
                    raise ValueError("ИИ вернул неверное количество или пустые задачи")
                # Claim the final write too: a worker whose lease expired cannot append items.
                saved = await session.execute(update(ContentPlanDay).where(
                    ContentPlanDay.id == day_id, ContentPlanDay.status == "running", ContentPlanDay.lease_token == token,
                ).values(status="done", error="", lease_until=None))
                if not saved.rowcount:
                    await session.rollback()
                    return
                session.add_all([ContentPlanItem(company_id=plan.company_id, plan_id=plan.id, planned_date=day.day,
                    title=item.title.strip(), description=item.description.strip(), position=index)
                    for index, item in enumerate(parsed.items)])
                await session.commit()
        except Exception as exc:
            await session.rollback()
            temporary_limit = isinstance(exc, (cache.RateLimited, jobs.RetryLater))
            permanent = isinstance(exc, limits.LimitExceeded)
            day = await session.get(ContentPlanDay, day_id)
            if temporary_limit:
                error = "Ожидание доступного лимита ИИ"
            elif permanent:
                error = str(exc)
            elif isinstance(exc, (ValueError, ValidationError)):
                error = "ИИ вернул некорректный список задач; повторите генерацию"
            else:
                error = "Не удалось получить контент-план от ИИ"
            values = dict(status="failed" if permanent or (day.attempts >= 3 and not temporary_limit) else "pending",
                          error=error, queued_at=None, lease_until=utcnow() + timedelta(seconds=60))
            if temporary_limit:
                values['attempts'] = max(0, day.attempts - 1)
            await session.execute(update(ContentPlanDay).where(ContentPlanDay.id == day_id,
                ContentPlanDay.status == "running", ContentPlanDay.lease_token == token).values(**values))
            await session.commit()
