"""Ядро бизнес-логики: согласование и публикация. Все правила «нельзя без согласования» живут здесь."""
import logging
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import cache, events, jobs, platforms
from .db import utcnow
from .config import settings
from .models import Approval, AuditLog, Post, SocialAccount, User
from .workflow import InvalidTransition, PostStatus, check_transition

log = logging.getLogger(__name__)
S = PostStatus


class NotFound(Exception):
    pass


async def audit(session: AsyncSession, company_id: int | None, user_id: int | None, action: str, details: str = "") -> None:
    session.add(AuditLog(company_id=company_id, user_id=user_id, action=action, details=details))
    await session.commit()


async def get_post(session: AsyncSession, company_id: int, post_id: int) -> Post:
    """Единственный способ получить пост по id: всегда с фильтром по компании."""
    post = (
        await session.execute(select(Post).where(Post.id == post_id, Post.company_id == company_id))
    ).scalar_one_or_none()
    if post is None:
        raise NotFound(f"post {post_id}")
    return post


async def _notify_approval(post_id: int) -> None:
    # через очередь notifications: недоступность Telegram не ломает бизнес-логику и не теряет уведомление
    await jobs.enqueue("notifications", "approval", {"post_id": post_id}, attempts=5)


async def notify_admins(text: str) -> None:
    await jobs.enqueue("notifications", "admins", {"text": text}, attempts=5)


async def _set_status(session: AsyncSession, post: Post, new: PostStatus) -> None:
    check_transition(post.status, new)
    post.status = new.value
    await session.commit()
    await events.publish("post.status", post_id=post.id, company_id=post.company_id, status=new.value)


async def submit_for_approval(session: AsyncSession, post: Post) -> Post:
    await _set_status(session, post, S.PENDING)
    await audit(session, post.company_id, post.created_by, "post.submitted", f"post={post.id} v{post.version}")
    await _notify_approval(post.id)
    return post


async def decide(
    session: AsyncSession, post: Post, user: User, decision: str, comment: str = "", version: int | None = None,
) -> Post:
    if post.status != S.PENDING.value:
        raise InvalidTransition(f"Пост в статусе {post.status}, решение невозможно")
    target = {"approve": S.APPROVED, "reject": S.REJECTED, "revise": S.REVISION}.get(decision)
    if target is None:
        raise ValueError("decision must be approve|reject|revise")
    expected = post.version if version is None else version
    missed = bool(target is S.APPROVED and post.task_run_id is not None and post.scheduled_at and post.scheduled_at <= utcnow())
    claimed = await session.execute(
        update(Post).where(Post.id == post.id, Post.status == S.PENDING.value, Post.version == expected)
        .values(status=target.value, needs_reschedule=missed), execution_options={"synchronize_session": False},
    )
    if claimed.rowcount != 1:
        await session.rollback()
        raise InvalidTransition("Материал уже изменён или решение принято. Откройте актуальную версию")
    session.add(
        Approval(
            company_id=post.company_id, post_id=post.id, post_version=expected,
            user_id=user.id, decision=decision, comment=comment,
        )
    )
    await session.commit()
    await session.refresh(post)
    await events.publish("post.status", post_id=post.id, company_id=post.company_id, status=post.status)
    await audit(session, post.company_id, user.id, f"post.{decision}", f"post={post.id} {comment}")
    if target is S.APPROVED and not post.needs_reschedule and (post.scheduled_at is None or post.scheduled_at <= utcnow()):
        await publish_post(session, post.id)
        await session.refresh(post)
        if post.status == S.FAILED.value:  # публикация не удалась: повторим позже (площадка могла быть недоступна)
            await jobs.enqueue("publishing", "publish", {"post_id": post.id}, delay_ms=60_000, attempts=4, backoff_ms=60_000)
    elif target is S.APPROVED and not post.needs_reschedule:  # отложенная публикация: задача сработает ровно в назначенное время
        delay = int((post.scheduled_at - utcnow()).total_seconds() * 1000)
        await jobs.enqueue("publishing", "publish", {"post_id": post.id}, delay_ms=delay, attempts=4, backoff_ms=60_000)
    await _notify_author(session, post, user, decision, comment)
    return post


async def _notify_author(session: AsyncSession, post: Post, decider: User, decision: str, comment: str) -> None:
    """Сотрудник, поставивший задачу, узнаёт в чате о решении по своему материалу."""
    if not post.created_by or post.created_by == decider.id:
        return
    author = await session.get(User, post.created_by)
    if author is None:
        return
    label = {"approve": "одобрен", "reject": "отклонён", "revise": "возвращён на доработку"}[decision]
    if post.needs_reschedule:
        label = "одобрен; время публикации прошло — выберите новое время в miniapp"
    elif post.status == S.PUBLISHED.value:
        label = "одобрен и опубликован"
    elif post.status == S.FAILED.value:
        label = "одобрен, но публикация не удалась"
    text = f"Материал #{post.id} {label}." + (f"\nКомментарий: {comment}" if comment else "")
    try:
        from .tg import notify_user

        await notify_user(author.telegram_id, text)
    except Exception:
        log.exception("notify_author failed")


def require_editable(post: Post) -> None:
    if post.status in (S.PUBLISHING.value, S.PUBLISHED.value, S.REJECTED.value):
        raise InvalidTransition(f"Пост в статусе {post.status} нельзя редактировать")


async def _edit_post(session: AsyncSession, post: Post, changes: dict, user_id: int | None, version: int | None) -> Post:
    """Сохраняет только выбранную часть и возвращает новую версию на согласование."""
    require_editable(post)
    expected = post.version if version is None else version
    changed = await session.execute(
        update(Post).where(
            Post.id == post.id, Post.version == expected,
            Post.status.in_([S.DRAFT.value, S.PENDING.value, S.APPROVED.value, S.REVISION.value, S.FAILED.value]),
        ).values(**changes, version=expected + 1, status=S.PENDING.value, error=""),
        execution_options={"synchronize_session": False},
    )
    if changed.rowcount != 1:
        await session.rollback()
        raise InvalidTransition("Материал уже изменён. Откройте актуальную версию и повторите действие")
    await session.commit()
    await session.refresh(post)
    await events.publish("post.status", post_id=post.id, company_id=post.company_id, status=post.status)
    await _notify_approval(post.id)
    action = "post.image_changed" if "image_url" in changes else "post.edited"
    await audit(session, post.company_id, user_id, action, f"post={post.id} v{post.version}")
    return post


async def edit_post_text(
    session: AsyncSession, post: Post, text: str, user_id: int | None = None, version: int | None = None,
) -> Post:
    if not text.strip() or len(text) > 4096:
        raise ValueError("Текст должен содержать от 1 до 4096 символов")
    return await _edit_post(session, post, {"text": text}, user_id, version)


async def edit_post_image(
    session: AsyncSession, post: Post, image_url: str, user_id: int | None = None, version: int | None = None,
) -> Post:
    return await _edit_post(session, post, {"image_url": image_url}, user_id, version)


async def publish_post(session: AsyncSession, post_id: int, notify: bool = True) -> Post | None:
    """Публикует пост. Работает только из approved; блокировка в Redis и атомарный захват защищают от дублей."""
    try:
        async with cache.lock(f"publish:{post_id}", ttl_sec=300):
            return await _publish_post(session, post_id, notify)
    except cache.LockBusy:
        return None  # этот пост уже публикует другой воркер


async def expire_scheduled_posts(session: AsyncSession, post_id: int | None = None) -> None:
    # Allow normal queue/tick latency, but never replay missed scheduled posts after an outage.
    cutoff = utcnow() - timedelta(seconds=max(60, settings.scheduler_interval_sec * 2))
    query = update(Post).where(Post.task_run_id.is_not(None), Post.scheduled_at < cutoff,
                               Post.status.in_([S.APPROVED.value, S.FAILED.value]), Post.needs_reschedule.is_(False))
    if post_id is not None:
        query = query.where(Post.id == post_id)
    await session.execute(query.values(needs_reschedule=True))
    await session.commit()


async def _publish_post(session: AsyncSession, post_id: int, notify: bool) -> Post | None:
    await expire_scheduled_posts(session, post_id)
    claimed = await session.execute(
        update(Post).where(Post.id == post_id, Post.status == S.APPROVED.value, Post.needs_reschedule.is_(False),
                           (Post.scheduled_at.is_(None)) | (Post.scheduled_at <= utcnow())).values(status=S.PUBLISHING.value)
    )
    await session.commit()
    if claimed.rowcount != 1:
        return None  # не одобрен или уже захвачен другим воркером
    post = await session.get(Post, post_id)
    await session.refresh(post)

    account = (
        await session.execute(
            select(SocialAccount).where(
                SocialAccount.company_id == post.company_id,
                SocialAccount.platform == post.platform,
                SocialAccount.active.is_(True), SocialAccount.analytics_only.is_(False),
            )
        )
    ).scalars().first()
    try:
        if account is None:
            raise RuntimeError(f"Не подключён аккаунт {post.platform}")
        from .platforms.base import PublishResult

        result = await platforms.REGISTRY[post.platform].publish(account, post.text, post.image_url)
        post.external_id = result.external_id if isinstance(result, PublishResult) else result
        post.published_channel_id = result.channel_id if isinstance(result, PublishResult) else account.channel_id
        post.published_at = utcnow()
        post.status, post.error = S.PUBLISHED.value, ""
        await session.commit()
        await audit(session, post.company_id, None, "post.published", f"post={post.id} ext={post.external_id}")
    except Exception as e:
        post.status, post.error = S.FAILED.value, str(e)
        await session.commit()
        await audit(session, post.company_id, None, "post.failed", f"post={post.id} {e}")
        if notify:
            await notify_admins(f"Ошибка публикации поста {post.id} (компания {post.company_id}): {e}")
    return post


async def publish_due(session: AsyncSession) -> int:
    await expire_scheduled_posts(session)
    ids = (
        await session.execute(
            select(Post.id).where(
                Post.status == S.APPROVED.value, Post.needs_reschedule.is_(False),
                (Post.scheduled_at.is_(None)) | (Post.scheduled_at <= utcnow()),
            )
        )
    ).scalars().all()
    for pid in ids:  # публикацию выполняют воркеры очереди publishing; dedup — чтобы тик не плодил дубли
        await jobs.enqueue("publishing", "publish", {"post_id": pid}, attempts=4, backoff_ms=60_000, dedup_id=f"publish-{pid}")
    return len(ids)
