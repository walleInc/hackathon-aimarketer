from datetime import date, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .. import content_plans, services
from ..auth import Ctx, get_ctx
from ..db import get_session
from ..models import Company, ContentPlan, ContentPlanDay, ContentPlanItem, Post

router = APIRouter(prefix="/api/content-plans", tags=["content-plans"])


class PlanIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    start_date: date
    end_date: date
    posts_per_day: int = Field(ge=1, le=10, strict=True)
    wishes: str = Field(default="", max_length=3000)

    @field_validator("title")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Укажите название")
        return value.strip()

    @model_validator(mode="after")
    def period(self):
        if not 0 <= (self.end_date - self.start_date).days <= 30:
            raise ValueError("Период должен составлять от 1 до 31 дня включительно")
        return self


class ItemIn(BaseModel):
    planned_date: date
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=3000)
    position: int = Field(default=0, ge=0)

    @field_validator("title", "description")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Заполните тему и описание")
        return value.strip()


class ItemEdit(ItemIn):
    version: int = Field(ge=1)


async def own_plan(session, ctx, plan_id):
    plan = await session.get(ContentPlan, plan_id)
    if plan is None or plan.company_id != ctx.require_company():
        raise HTTPException(404, "Контент-план не найден")
    return plan


async def own_item(session, ctx, item_id):
    item = await session.get(ContentPlanItem, item_id)
    if item is None or item.deleted or item.company_id != ctx.require_company():
        raise HTTPException(404, "Задача плана не найдена")
    return item


def item_out(item, posts=()):
    return {**{k: getattr(item, k) for k in ("id", "plan_id", "planned_date", "title", "description", "position", "version")},
            "posts": [{"id": p.id, "status": p.status} for p in posts]}


def plan_out(plan, days):
    done = sum(d.status == "done" for d in days)
    failed = sum(d.status == "failed" for d in days)
    return {**{k: getattr(plan, k) for k in ("id", "title", "start_date", "end_date", "posts_per_day", "wishes", "created_by", "created_at")},
            "completed_days": done, "total_days": len(days),
            "status": "ready" if done == len(days) else "failed" if done + failed == len(days) else "generating",
            "days": [{"date": d.day, "status": d.status, "error": d.error} for d in days]}


def check_date(plan, value):
    if not plan.start_date <= value <= plan.end_date:
        raise HTTPException(422, "Дата задачи должна входить в период плана")


@router.get("")
async def list_plans(limit: int = Query(50, ge=1, le=100), ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    plans = (await session.execute(select(ContentPlan).where(ContentPlan.company_id == ctx.require_company()).order_by(ContentPlan.id.desc()).limit(limit))).scalars().all()
    if not plans:
        return []
    days = (await session.execute(select(ContentPlanDay).where(ContentPlanDay.plan_id.in_([p.id for p in plans])).order_by(ContentPlanDay.day))).scalars().all()
    return [plan_out(p, [d for d in days if d.plan_id == p.id]) for p in plans]


@router.post("", status_code=202)
async def create_plan(body: PlanIn, background: BackgroundTasks, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    ctx.require_creator()
    cid = ctx.require_company()
    if await session.get(Company, cid) is None:
        raise HTTPException(404, "Компания не найдена")
    plan = ContentPlan(company_id=cid, created_by=ctx.user.id, **body.model_dump())
    session.add(plan)
    await session.flush()
    days = [ContentPlanDay(company_id=cid, plan_id=plan.id, day=body.start_date + timedelta(days=i))
            for i in range((body.end_date - body.start_date).days + 1)]
    session.add_all(days)
    await session.commit()
    await services.audit(session, cid, ctx.user.id, "content_plan.created", f"plan={plan.id}")
    background.add_task(content_plans.dispatch_days, plan.id)
    return {"id": plan.id}


@router.get("/{plan_id}")
async def get_plan(plan_id: int, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    plan = await own_plan(session, ctx, plan_id)
    days = (await session.execute(select(ContentPlanDay).where(ContentPlanDay.plan_id == plan_id).order_by(ContentPlanDay.day))).scalars().all()
    items = (await session.execute(select(ContentPlanItem).where(ContentPlanItem.plan_id == plan_id, ContentPlanItem.deleted.is_(False)).order_by(ContentPlanItem.planned_date, ContentPlanItem.position, ContentPlanItem.id))).scalars().all()
    posts = (await session.execute(select(Post).join(ContentPlanItem, Post.content_plan_item_id == ContentPlanItem.id).where(ContentPlanItem.plan_id == plan_id).order_by(Post.id.desc()))).scalars().all()
    return {**plan_out(plan, days), "items": [item_out(i, [p for p in posts if p.content_plan_item_id == i.id]) for i in items]}


@router.post("/{plan_id}/retry", status_code=202)
async def retry_plan(plan_id: int, background: BackgroundTasks, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    ctx.require_creator()
    await own_plan(session, ctx, plan_id)
    await session.execute(update(ContentPlanDay).where(ContentPlanDay.plan_id == plan_id, ContentPlanDay.status == "failed")
                          .values(status="pending", attempts=0, lease_until=None, queued_at=None, error=""))
    await session.commit()
    background.add_task(content_plans.dispatch_days, plan_id)
    return {"ok": True}


@router.post("/{plan_id}/items", status_code=201)
async def add_item(plan_id: int, body: ItemIn, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    ctx.require_creator()
    plan = await own_plan(session, ctx, plan_id)
    check_date(plan, body.planned_date)
    item = ContentPlanItem(company_id=plan.company_id, plan_id=plan.id, **body.model_dump())
    session.add(item)
    await session.commit()
    return item_out(item)


@router.patch("/items/{item_id}")
async def edit_item(item_id: int, body: ItemEdit, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    ctx.require_creator()
    item = await own_item(session, ctx, item_id)
    check_date(await own_plan(session, ctx, item.plan_id), body.planned_date)
    claimed = await session.execute(update(ContentPlanItem).where(
        ContentPlanItem.id == item.id, ContentPlanItem.deleted.is_(False), ContentPlanItem.version == body.version,
    ).values(**body.model_dump(exclude={"version"}), version=ContentPlanItem.version + 1))
    if not claimed.rowcount:
        await session.rollback()
        raise HTTPException(409, "Задача уже изменена; обновите план")
    await session.commit()
    await session.refresh(item)
    return item_out(item)


@router.delete("/items/{item_id}")
async def delete_item(item_id: int, version: int = Query(ge=1), ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    ctx.require_creator()
    item = await own_item(session, ctx, item_id)
    claimed = await session.execute(update(ContentPlanItem).where(ContentPlanItem.id == item.id,
        ContentPlanItem.deleted.is_(False), ContentPlanItem.version == version).values(deleted=True, version=ContentPlanItem.version + 1))
    if not claimed.rowcount:
        await session.rollback()
        raise HTTPException(409, "Задача уже изменена; обновите план")
    await session.commit()
    return {"ok": True}
