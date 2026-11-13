from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import agent, limits, services
from ..auth import Ctx, get_ctx
from ..db import get_session
from ..models import Company, Post, Task
from ..workflow import InvalidTransition

router = APIRouter(prefix="/api")


def post_out(p: Post) -> dict:
    return {
        "id": p.id, "platform": p.platform, "text": p.text, "image_url": p.image_url, "status": p.status,
        "version": p.version, "scheduled_at": p.scheduled_at, "error": p.error, "created_at": p.created_at,
        "check_notes": p.check_notes,
    }


async def _post(session: AsyncSession, ctx: Ctx, post_id: int) -> Post:
    try:
        return await services.get_post(session, ctx.require_company(), post_id)
    except services.NotFound:
        raise HTTPException(404, "Пост не найден")


@router.get("/me")
async def me(ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    company = await session.get(Company, ctx.company_id) if ctx.company_id else None
    return {
        "telegram_id": ctx.user.telegram_id, "role": ctx.user.role,
        "company": {"id": company.id, "name": company.name} if company else None,
    }


@router.get("/posts")
async def list_posts(status: str | None = None, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    q = select(Post).where(Post.company_id == ctx.require_company()).order_by(Post.id.desc()).limit(100)
    if status:
        q = q.where(Post.status == status)
    return [post_out(p) for p in (await session.execute(q)).scalars()]


@router.get("/posts/{post_id}")
async def get_post(post_id: int, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    return post_out(await _post(session, ctx, post_id))


class DecisionIn(BaseModel):
    decision: Literal["approve", "reject", "revise"]
    comment: str = ""


@router.post("/posts/{post_id}/decision")
async def decide(post_id: int, body: DecisionIn, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    if not ctx.can_approve:
        raise HTTPException(403, "Согласовывать может только администратор компании")
    post = await _post(session, ctx, post_id)
    if body.decision == "revise" and body.comment:
        # бюджет проверяем ДО смены статуса, чтобы пост не застрял в «на доработке»
        try:
            await limits.check_token_budget(session, await session.get(Company, post.company_id))
        except limits.LimitExceeded as e:
            raise HTTPException(429, str(e))
    try:
        post = await services.decide(session, post, ctx.user, body.decision, body.comment)
        if body.decision == "revise" and body.comment:
            post = await agent.revise_post(session, post, body.comment, ctx.user.id)
    except InvalidTransition as e:
        raise HTTPException(409, str(e))
    return post_out(post)


class EditIn(BaseModel):
    text: str


@router.patch("/posts/{post_id}")
async def edit(post_id: int, body: EditIn, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    if not ctx.can_approve:
        raise HTTPException(403, "Править текст может только администратор компании")
    post = await _post(session, ctx, post_id)
    try:
        post = await services.edit_post_text(session, post, body.text, ctx.user.id)
    except InvalidTransition as e:
        raise HTTPException(409, str(e))
    return post_out(post)


class MessageIn(BaseModel):
    text: str


@router.post("/agent/message")
async def agent_message(body: MessageIn, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    ctx.require_creator()
    res = await agent.handle_message(session, ctx.require_company(), ctx.user, body.text)
    return {"reply": res.reply, "post_id": res.post_id}


class TaskIn(BaseModel):
    prompt: str
    interval_minutes: int = 1440


@router.get("/tasks")
async def list_tasks(ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    rows = (await session.execute(select(Task).where(Task.company_id == ctx.require_company()))).scalars()
    return [
        {"id": t.id, "prompt": t.prompt, "interval_minutes": t.interval_minutes, "active": t.active, "last_run": t.last_run}
        for t in rows
    ]


@router.post("/tasks")
async def create_task(body: TaskIn, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    ctx.require_creator()
    task = Task(company_id=ctx.require_company(), prompt=body.prompt, interval_minutes=max(body.interval_minutes, 1))
    session.add(task)
    await session.commit()
    await services.audit(session, task.company_id, ctx.user.id, "task.created", f"task={task.id}")
    return {"id": task.id}
