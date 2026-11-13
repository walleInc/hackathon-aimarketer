"""Ядро бизнес-логики: согласование и публикация. Все правила «нельзя без согласования» живут здесь."""
import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from . import platforms
from .db import utcnow
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
    try:
        from .tg import notify_approval

        await notify_approval(post_id)
    except Exception:  # недоступность Telegram не должна ломать бизнес-логику
        log.exception("notify_approval failed")


async def notify_admins(text: str) -> None:
    try:
        from .tg import notify_admins as _n

        await _n(text)
    except Exception:
        log.exception("notify_admins failed")


async def _set_status(session: AsyncSession, post: Post, new: PostStatus) -> None:
    check_transition(post.status, new)
    post.status = new.value
    await session.commit()


async def submit_for_approval(session: AsyncSession, post: Post) -> Post:
    await _set_status(session, post, S.PENDING)
    await audit(session, post.company_id, post.created_by, "post.submitted", f"post={post.id} v{post.version}")
    await _notify_approval(post.id)
    return post


async def decide(session: AsyncSession, post: Post, user: User, decision: str, comment: str = "") -> Post:
    if post.status != S.PENDING.value:
        raise InvalidTransition(f"Пост в статусе {post.status}, решение невозможно")
    target = {"approve": S.APPROVED, "reject": S.REJECTED, "revise": S.REVISION}.get(decision)
    if target is None:
        raise ValueError("decision must be approve|reject|revise")
    session.add(
        Approval(
            company_id=post.company_id, post_id=post.id, post_version=post.version,
            user_id=user.id, decision=decision, comment=comment,
        )
    )
    await _set_status(session, post, target)
    await audit(session, post.company_id, user.id, f"post.{decision}", f"post={post.id} {comment}")
    if target is S.APPROVED and (post.scheduled_at is None or post.scheduled_at <= utcnow()):
        await publish_post(session, post.id)
        await session.refresh(post)
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
    if post.status == S.PUBLISHED.value:
        label = "одобрен и опубликован"
    elif post.status == S.FAILED.value:
        label = "одобрен, но публикация не удалась"
    text = f"Материал #{post.id} {label}." + (f"\nКомментарий: {comment}" if comment else "")
    try:
        from .tg import notify_user

        await notify_user(author.telegram_id, text)
    except Exception:
        log.exception("notify_author failed")


async def edit_post_text(session: AsyncSession, post: Post, text: str, user_id: int | None = None) -> Post:
    """Любая правка текста увеличивает версию и требует повторного согласования."""
    if post.status in (S.PUBLISHING.value, S.PUBLISHED.value, S.REJECTED.value):
        raise InvalidTransition(f"Пост в статусе {post.status} нельзя редактировать")
    post.text = text
    post.version += 1
    await session.commit()
    if post.status == S.REVISION.value:
        await _set_status(session, post, S.DRAFT)
    if post.status == S.DRAFT.value:
        await submit_for_approval(session, post)
    elif post.status == S.PENDING.value:
        await _notify_approval(post.id)
    else:  # approved / failed -> снова на согласование
        await _set_status(session, post, S.PENDING)
        await _notify_approval(post.id)
    await audit(session, post.company_id, user_id, "post.edited", f"post={post.id} v{post.version}")
    return post


async def publish_post(session: AsyncSession, post_id: int) -> Post | None:
    """Публикует пост. Работает только из approved; атомарный захват защищает от дублей."""
    claimed = await session.execute(
        update(Post).where(Post.id == post_id, Post.status == S.APPROVED.value).values(status=S.PUBLISHING.value)
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
                SocialAccount.active.is_(True),
            )
        )
    ).scalars().first()
    try:
        if account is None:
            raise RuntimeError(f"Не подключён аккаунт {post.platform}")
        post.external_id = await platforms.REGISTRY[post.platform].publish(account, post.text, post.image_url)
        post.status, post.error = S.PUBLISHED.value, ""
        await session.commit()
        await audit(session, post.company_id, None, "post.published", f"post={post.id} ext={post.external_id}")
    except Exception as e:
        post.status, post.error = S.FAILED.value, str(e)
        await session.commit()
        await audit(session, post.company_id, None, "post.failed", f"post={post.id} {e}")
        await notify_admins(f"Ошибка публикации поста {post.id} (компания {post.company_id}): {e}")
    return post


async def publish_due(session: AsyncSession) -> int:
    ids = (
        await session.execute(
            select(Post.id).where(
                Post.status == S.APPROVED.value,
                (Post.scheduled_at.is_(None)) | (Post.scheduled_at <= utcnow()),
            )
        )
    ).scalars().all()
    for pid in ids:
        await publish_post(session, pid)
    return len(ids)
