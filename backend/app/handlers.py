"""Обработчики очередей BullMQ: уведомления, публикация, задачи по расписанию, AI, документы, аналитика, модерация."""
import json
import logging
from sqlalchemy import func, select

from . import agent, cache, context_files, limits, scheduler, services, storage
from .config import settings
from .db import SessionLocal, utcnow
from .jobs import JobCtx, PermanentFailure, RetryLater, handler, org_slot
from .models import AgentRun, Company, Post, Task, UsageCost
from .workflow import PostStatus

log = logging.getLogger(__name__)


# ---------- notifications ----------

@handler("notifications", "approval")
async def notify_approval(data: dict, ctx: JobCtx):
    from . import tg

    await tg.notify_approval(int(data["post_id"]))


@handler("notifications", "admins")
async def notify_admins(data: dict, ctx: JobCtx):
    from . import tg

    await tg.notify_admins(data["text"])


# ---------- publishing ----------

@handler("publishing", "publish")
async def publish(data: dict, ctx: JobCtx):
    """Публикует одобренный пост; при сбое площадки повторяет с нарастающей паузой."""
    post_id = int(data["post_id"])
    async with SessionLocal() as session:
        post = await session.get(Post, post_id)
        if post is None:
            return {"skipped": "not found"}
        if post.status == PostStatus.FAILED.value:  # повтор после неудачной попытки
            post.status = PostStatus.APPROVED.value
            await session.commit()
        if post.status != PostStatus.APPROVED.value:
            return {"skipped": post.status}  # уже опубликован, отклонён или правится
        if post.needs_reschedule:
            return {"skipped": "requires rescheduling"}
        if post.scheduled_at and post.scheduled_at > utcnow():
            raise RetryLater(int((post.scheduled_at - utcnow()).total_seconds() * 1000))
        result = await services.publish_post(session, post_id, notify=ctx.is_last)
        if result is None:
            await session.refresh(post)
            if post.needs_reschedule:
                return {"skipped": "missed publication time"}
        if result is None:  # пост публикует другой воркер: вернёмся и проверим итог (успех — пропустим, сбой — повторим)
            raise RetryLater(5000)
        if result.status == PostStatus.FAILED.value and not ctx.is_last:
            raise RuntimeError(result.error)  # BullMQ повторит позже
        return {"status": result.status}


# ---------- scheduled-tasks ----------

@handler("scheduled-tasks", "tick")
async def tick(data: dict, ctx: JobCtx):
    await scheduler.run_tick()


# ---------- ai-generation ----------

@handler("ai-generation", "agent_run")
async def agent_run(data: dict, ctx: JobCtx):
    from . import runs
    async with SessionLocal() as session:
        try:
            run = await session.get(AgentRun, int(data["run_id"]))
            if run is None:
                return {"skipped": True}
            async with org_slot("ai-generation", run.company_id):
                run = await runs.execute(session, run.id)
            return {"run_id": run.id, "status": run.status, "post_id": run.post_id} if run else {"skipped": True}
        except cache.LockBusy:
            raise RetryLater(3000)


@handler("notifications", "run_result")
async def run_result(data: dict, ctx: JobCtx):
    from . import runs
    try:
        await runs.deliver(int(data["delivery_id"]))
    except cache.LockBusy:
        raise RetryLater(3000)

@handler("ai-generation", "run_task")
async def run_task(data: dict, ctx: JobCtx):
    from .task_execution import execute_run
    if "run_id" in data:
        result = await execute_run(int(data["run_id"]))
        from . import runs
        await runs.sync_task_results()
        return result
    # Jobs queued by the previous application version remain executable.
    async with SessionLocal() as session:
        task = await session.get(Task, int(data["task_id"]))
        if task is None or not task.active or task.deleted:
            return {"skipped": True}
        await agent.handle_message(session, task.company_id, None, f"Подготовь пост сейчас: {task.prompt}")


# ---------- document-processing ----------

@handler("document-processing", "extract")
async def extract_document(data: dict, ctx: JobCtx):
    """Достаёт текст из загруженного файла контекста и кладёт в кэш, чтобы запросы к AI не ждали разбора."""
    if not storage.enabled():
        raise PermanentFailure("хранилище файлов не настроено")
    files = {f.name: f for f in await storage.list_files(int(data["company_id"]))}
    f = files.get(data["filename"])
    if f is None:
        return {"skipped": "file not found"}
    try:
        text = await context_files.file_text(f)
    except context_files.UnsupportedFile as e:
        raise PermanentFailure(str(e))
    return {"chars": len(text)}


# ---------- analytics ----------

SNAPSHOT_TTL = 2 * 3600


async def build_snapshot(session, company: Company) -> dict:
    day = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    month = day.replace(day=1)
    by_status = dict(
        (await session.execute(select(Post.status, func.count()).where(Post.company_id == company.id).group_by(Post.status))).all()
    )
    cost = (await session.execute(
        select(func.coalesce(func.sum(UsageCost.cost_usd), 0.0), func.coalesce(func.sum(UsageCost.tokens), 0))
        .where(UsageCost.company_id == company.id, UsageCost.created_at >= month)
    )).one()
    return {
        "company_id": company.id, "name": company.name, "posts_by_status": by_status,
        "posts_today": await limits.posts_today(session, company.id),
        "month_cost_usd": round(float(cost[0]), 4), "month_tokens": int(cost[1]),
        "token_limit": company.monthly_token_limit, "collected_at": utcnow().isoformat(),
    }


@handler("analytics", "collect")
async def collect(data: dict, ctx: JobCtx):
    """Сводка по каждой организации: публикации, расходы, лимиты. Хранится в Redis, обновляется раз в час."""
    async with SessionLocal() as session:
        stmt = select(Company)
        if data.get("company_id"):
            stmt = stmt.where(Company.id == int(data["company_id"]))
        companies = (await session.execute(stmt)).scalars().all()
        for c in companies:
            snap = await build_snapshot(session, c)
            await cache.get_redis().set(f"{cache.PREFIX}analytics:{c.id}", json.dumps(snap, ensure_ascii=False), ex=SNAPSHOT_TTL)
    return {"companies": len(companies)}


async def get_snapshot(session, company: Company) -> dict:
    raw = await cache.get_redis().get(f"{cache.PREFIX}analytics:{company.id}")
    return json.loads(raw) if raw else await build_snapshot(session, company)


# ---------- moderation ----------

MODERATION_PROMPT = (
    "Ты модератор сообщества компании. Классифицируй входящее сообщение: spam | toxic | question | feedback | ok. "
    'Верни JSON: {"label": "...", "reason": "кратко", "suggested_reply": "ответ по правилам бренда или пустая строка"}'
)


@handler("moderation", "check")
async def moderate(data: dict, ctx: JobCtx):
    """Анализ комментария или входящего сообщения: метка и черновик ответа (отправку подтверждает человек)."""
    from .llm import get_llm

    company_id = int(data["company_id"])
    await cache.rate_limit(f"mod:{company_id}", settings.ai_rate_limit_per_min * 3)
    async with SessionLocal() as session:
        company = await session.get(Company, company_id)
        if company is None:
            raise PermanentFailure("организация не найдена")
        try:
            await limits.check_token_budget(session, company)
        except limits.LimitExceeded as e:
            raise PermanentFailure(str(e))
        system = await agent._system_prompt(session, company_id, json_mode=False)
        res = await get_llm().complete(
            system + "\n" + MODERATION_PROMPT, [{"role": "user", "content": str(data["text"])[:2000]}], json_mode=True
        )
        await agent._record_llm(session, company_id, res)
        verdict = agent._parse(res.text)
        return {"label": verdict.get("label", "ok"), "reason": verdict.get("reason", ""),
                "suggested_reply": verdict.get("suggested_reply", "")}



@handler("ai-generation", "content_plan_day")
async def content_plan_day(data: dict, ctx: JobCtx):
    from .content_plans import generate_day
    await generate_day(int(data["day_id"]))
