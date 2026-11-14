"""Persistent execution and notification outbox shared by bot, API and scheduler."""
import asyncio
import logging
from datetime import timedelta

from sqlalchemy import select, update

from . import cache, jobs, services
from .db import SessionLocal, utcnow
from .media import media_path
from .models import AgentRun, Message, Post, RunDelivery, Task, TaskRun, User

log = logging.getLogger(__name__)


def out(run):
    return {key: getattr(run, key) for key in (
        "id", "kind", "prompt", "status", "result", "image_url", "error", "post_id", "task_id", "parent_run_id",
        "created_at", "started_at", "finished_at",
    )}


async def create(session, company_id, user_id, prompt, *, kind="message", post_id=None, task_id=None,
                 parent_run_id=None, expected_version=None, reference_url=""):
    if parent_run_id:
        parent = await session.get(AgentRun, parent_run_id)
        shared = parent is not None and parent.user_id is None and parent.task_id is not None
        if parent is None or parent.company_id != company_id or (parent.user_id != user_id and not shared):
            raise services.NotFound("Предыдущее выполнение не найдено")
    if post_id:
        post = await services.get_post(session, company_id, post_id)
        if kind in {"revise", "image"} and expected_version is None:
            expected_version = post.version
    run = AgentRun(company_id=company_id, user_id=user_id, prompt=prompt, kind=kind, post_id=post_id,
                   task_id=task_id, parent_run_id=parent_run_id, expected_version=expected_version,
                   reference_url=reference_url)
    session.add(run)
    await session.flush()
    session.add(Message(company_id=company_id, user_id=user_id, role="user", content=prompt,
                        run_id=run.id, post_id=post_id))
    await session.commit()
    return run


async def dispatch(run_id):
    await jobs.enqueue("ai-generation", "agent_run", {"run_id": run_id}, dedup_id=f"agent-run-{run_id}")


async def execute_sync(session, run_id, **kwargs):
    """Legacy synchronous endpoints must return a final response if a dialogue is busy."""
    try:
        return await execute(session, run_id, **kwargs)
    except cache.LockBusy:
        run = await session.get(AgentRun, run_id)
        await finish(session, run, "Предыдущая задача ещё выполняется. Повторите запрос после её завершения.",
                     "Предыдущая задача ещё выполняется")
        await enqueue_deliveries(session, run_id)
        if kwargs.get("propagate"):
            raise
        return run


async def finish(session, run, reply, error=""):
    image_url = ""
    if run.post_id and not error:
        post = await session.get(Post, run.post_id)
        image_url = post.image_url if post else ""
    claimed = await session.execute(update(AgentRun).where(
        AgentRun.id == run.id, AgentRun.status.in_(["queued", "running"]),
    ).values(result=reply, error=error, status="failed" if error else "completed",
             finished_at=utcnow(), image_url=image_url), execution_options={"synchronize_session": False})
    if claimed.rowcount != 1:
        await session.rollback()
        await session.refresh(run)
        return
    await session.refresh(run)
    session.add(Message(company_id=run.company_id, user_id=run.user_id, role="assistant", content=reply,
                        run_id=run.id, post_id=run.post_id))
    recipients = []
    if run.user_id:
        user = await session.get(User, run.user_id)
        if user and user.company_id == run.company_id:
            recipients = [user.telegram_id]
    elif run.task_id:
        recipients = list((await session.execute(select(User.telegram_id).where(
            User.company_id == run.company_id, User.role == "approver"))).scalars())
    for recipient in set(recipients):
        session.add(RunDelivery(run_id=run.id, telegram_id=recipient))
    await session.commit()  # result, final message and outbox are atomic


def post_result(post):
    labels = {"pending_approval": "подготовлен и отправлен на согласование", "published": "опубликован",
              "approved": "одобрен", "rejected": "отклонён", "revision": "на доработке"}
    return f"Готово. Материал #{post.id}, версия {post.version}: {labels.get(post.status, post.status)}.\n\n{post.text}"


async def execute(session, run_id, *, reference=None, propagate=False):
    from . import agent

    run = await session.get(AgentRun, run_id)
    if not run or run.status != "queued":
        return run
    # Serialize personal dialogue, while the atomic claim also protects against duplicate queue jobs.
    async with cache.lock(f"agent-user:{run.company_id}:{run.user_id or 'scheduled'}", ttl_sec=960):
        claim = await session.execute(update(AgentRun).where(AgentRun.id == run_id, AgentRun.status == "queued")
                                      .values(status="running", started_at=utcnow()))
        await session.commit()
        await session.refresh(run)
        if claim.rowcount != 1:
            return run
        failure = None
        try:
            async with asyncio.timeout(900):
                user = await session.get(User, run.user_id) if run.user_id else None
                if run.user_id and (user is None or user.company_id != run.company_id or user.role not in {"approver", "member"}):
                    raise ValueError("Доступ к компании отозван")
                if run.kind in {"revise", "image"}:
                    if user is None or user.role != "approver":
                        raise ValueError("Изменять материал может только администратор компании")
                    post = await services.get_post(session, run.company_id, run.post_id)
                    if run.expected_version is not None and post.version != run.expected_version:
                        raise services.InvalidTransition("Версия устарела. Откройте актуальный материал")
                    if run.kind == "revise":
                        post = await agent._revise_post(session, post, run.prompt, run.user_id)
                    else:
                        post = await agent._regenerate_post_image(session, post, run.prompt, run.user_id, run.expected_version)
                    reply = post_result(post)
                else:
                    if run.task_id:
                        task = await session.get(Task, run.task_id)
                        if not task or task.company_id != run.company_id or not task.active:
                            raise ValueError("Регулярная задача отключена или удалена")
                    if reference is None and run.reference_url:
                        reference = media_path(run.reference_url).read_bytes()
                    result = await agent._handle_message(session, run.company_id, user, run.prompt,
                                                         reference=reference, run=run)
                    run.post_id = result.post_id
                    reply = result.reply
                    if result.error:
                        raise ValueError(result.reply)
                await finish(session, run, reply)
        except Exception as exc:
            failure = exc
            log.exception("AI run %s failed", run_id)
            await session.rollback()
            await session.refresh(run)
            from .limits import LimitExceeded
            known = isinstance(exc, (ValueError, LimitExceeded, cache.RateLimited, services.InvalidTransition))
            error = str(exc) if known else "Не удалось выполнить задачу из-за сбоя сервиса ИИ"
            await finish(session, run, f"Задача не выполнена: {error}. Можно повторить запрос.", error)
        try:
            await enqueue_deliveries(session, run.id)
        except Exception:
            log.exception("outbox enqueue failed for run %s; maintenance will retry", run.id)
        if failure and propagate:
            raise failure
        return run


async def enqueue_deliveries(session, run_id=None):
    query = select(RunDelivery.id).where(RunDelivery.status == "pending")
    if run_id is not None:
        query = query.where(RunDelivery.run_id == run_id)
    ids = list((await session.execute(query.limit(100))).scalars())
    for delivery_id in ids:
        await jobs.enqueue("notifications", "run_result", {"delivery_id": delivery_id}, attempts=5,
                           dedup_id=f"run-delivery-{delivery_id}")


async def deliver(delivery_id):
    from . import tg

    async with cache.lock(f"run-delivery:{delivery_id}", ttl_sec=600):
        async with SessionLocal() as session:
            delivery = await session.get(RunDelivery, delivery_id)
            if not delivery or delivery.status != "pending":
                return
            if tg.bot is None:
                return  # retained in outbox until Telegram is configured
            run = await session.get(AgentRun, delivery.run_id)
            user = (await session.execute(select(User).where(User.telegram_id == delivery.telegram_id,
                                                            User.company_id == run.company_id))).scalar_one_or_none()
            if not user or (run.user_id is not None and user.id != run.user_id) or (run.user_id is None and user.role != "approver"):
                delivery.status = "cancelled"
                await session.commit()
                return
            chunks = tg.split_text(f"Задача #{run.id}\n{run.result}")
            delivery.attempts += 1
            await session.commit()
            try:
                # A separate photo counts as the first chunk; retries resume after it.
                has_image = bool(run.image_url and run.status == "completed")
                if has_image and delivery.next_chunk == 0:
                    from aiogram.types import FSInputFile
                    photo = FSInputFile(media_path(run.image_url)) if run.image_url.startswith("/media/") else run.image_url
                    await tg.bot.send_photo(delivery.telegram_id, photo)
                    delivery.next_chunk = 1
                    await session.commit()
                offset = 1 if has_image else 0
                for i, chunk in enumerate(chunks):
                    if i + offset < delivery.next_chunk:
                        continue
                    await tg.bot.send_message(delivery.telegram_id, chunk)
                    delivery.next_chunk = i + offset + 1
                    await session.commit()
                delivery.status, delivery.error, delivery.sent_at = "sent", "", utcnow()
                await session.commit()
            except Exception as exc:
                delivery.error = type(exc).__name__
                await session.commit()
                raise  # queue retries must see transport failures


async def sync_task_results():
    try:
        async with cache.lock("task-result-sync", ttl_sec=120):
            async with SessionLocal() as session:
                results = (await session.execute(select(TaskRun).where(
                    TaskRun.status.in_(["succeeded", "failed"]),
                    ~TaskRun.id.in_(select(AgentRun.task_run_id).where(AgentRun.task_run_id.is_not(None))),
                ).limit(100))).scalars().all()
                for result in results:
                    task = await session.get(Task, result.task_id)
                    if not task:
                        continue
                    run = AgentRun(company_id=result.company_id, user_id=task.created_by, prompt=task.prompt,
                        kind="scheduled", task_id=task.id, task_run_id=result.id, post_id=result.post_id,
                        status="running", started_at=result.started_at)
                    session.add(run)
                    await session.flush()
                    session.add(Message(company_id=run.company_id, user_id=run.user_id, run_id=run.id,
                                        role="user", content=run.prompt))
                    post = await session.get(Post, result.post_id) if result.post_id else None
                    text = post_result(post) if post else result.result or result.error
                    await finish(session, run, text, result.error if result.status == "failed" else "")
                    await enqueue_deliveries(session, run.id)
    except cache.LockBusy:
        pass


async def maintain():
    """Redis is transport; the DB is the source of truth across process restarts."""
    await sync_task_results()
    async with SessionLocal() as session:
        stale = (await session.execute(select(AgentRun).where(
            AgentRun.status == "running", AgentRun.started_at < utcnow() - timedelta(minutes=16)))).scalars().all()
        for run in stale:
            # Never regenerate blindly after a crash: a material may already have been committed.
            post = await session.get(Post, run.post_id) if run.post_id else None
            if post and post.status == "pending_approval" and (
                run.kind not in {"revise", "image"} or
                (run.expected_version is not None and post.version > run.expected_version)
            ):
                await finish(session, run, post_result(post))
            else:
                await finish(session, run, "Работа прервана. Проверьте материалы перед повторным запросом.", "Выполнение прервано")
        queued = list((await session.execute(select(AgentRun.id).where(AgentRun.status == "queued").limit(100))).scalars())
        for run_id in queued:
            await dispatch(run_id)
        await enqueue_deliveries(session)
