from typing import Literal
from datetime import timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import agent, cache, limits, post_images, services
from ..media import media_path
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
        "published_at": p.published_at.replace(tzinfo=timezone.utc) if p.published_at else None,
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
    version: int | None = Field(default=None, ge=1)


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
        post = await services.decide(session, post, ctx.user, body.decision, body.comment, body.version)
        if body.decision == "revise" and body.comment:
            post = await agent.revise_post(session, post, body.comment, ctx.user.id)
    except InvalidTransition as e:
        raise HTTPException(409, str(e))
    return post_out(post)


class EditIn(BaseModel):
    text: str = Field(min_length=1, max_length=4096)
    version: int | None = Field(default=None, ge=1)


@router.patch("/posts/{post_id}")
async def edit(post_id: int, body: EditIn, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    if not ctx.can_approve:
        raise HTTPException(403, "Править текст может только администратор компании")
    post = await _post(session, ctx, post_id)
    try:
        post.check_notes = "Текст изменён вручную; требуется проверка согласующего"
        post = await services.edit_post_text(session, post, body.text, ctx.user.id, body.version)
    except InvalidTransition as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    return post_out(post)


class RegenerateImageIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    version: int | None = Field(default=None, ge=1)


@router.post("/posts/{post_id}/image/regenerate")
async def regenerate_image(
    post_id: int, body: RegenerateImageIn, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session),
):
    if not ctx.can_approve:
        raise HTTPException(403, "Менять изображение может только администратор компании")
    post = await _post(session, ctx, post_id)
    try:
        post = await agent.regenerate_post_image(session, post, body.prompt, ctx.user.id, body.version)
    except (cache.LockBusy, InvalidTransition) as e:
        raise HTTPException(409, str(e) if isinstance(e, InvalidTransition) else "Картинка уже генерируется")
    except (limits.LimitExceeded, cache.RateLimited) as e:
        raise HTTPException(429, str(e))
    except ValueError as e:
        raise HTTPException(422, str(e))
    return post_out(post)


@router.post("/posts/{post_id}/image")
async def upload_image(
    post_id: int, file: UploadFile = File(...), version: int | None = Form(None),
    ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session),
):
    if not ctx.can_approve:
        raise HTTPException(403, "Менять изображение может только администратор компании")
    post = await _post(session, ctx, post_id)
    url = None
    try:
        services.require_editable(post)
        data = await file.read(post_images.MAX_IMAGE_BYTES + 1)
        url = post_images.save_upload(data)
        post = await services.edit_post_image(session, post, url, ctx.user.id, version)
    except (ValueError, InvalidTransition) as e:
        if url:
            media_path(url).unlink(missing_ok=True)
        raise HTTPException(409 if isinstance(e, InvalidTransition) else 422, str(e))
    return post_out(post)


class MessageIn(BaseModel):
    text: str


@router.post("/agent/message")
async def agent_message(body: MessageIn, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    ctx.require_creator()
    res = await agent.handle_message(session, ctx.require_company(), ctx.user, body.text)
    return {"reply": res.reply, "post_id": res.post_id}


@router.post("/agent/message/reference")
async def agent_message_reference(
    text: str = Form(..., min_length=1, max_length=4000),
    reference: UploadFile = File(...),
    ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session),
):
    ctx.require_creator()
    if not text.strip():
        raise HTTPException(422, "Укажите задание для поста")
    try:
        data = post_images.reference_bytes(await reference.read(post_images.MAX_IMAGE_BYTES + 1))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    finally:
        await reference.close()
    try:
        res = await agent.handle_message(session, ctx.require_company(), ctx.user, text.strip(), reference=data)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
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
