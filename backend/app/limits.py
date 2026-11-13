"""Бизнес-ограничения: расходы и количество публикаций (защита от несанкционированных расходов)."""
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .db import utcnow
from .models import AuditLog, Company, Post, UsageCost


class LimitExceeded(Exception):
    pass


def _month_start() -> datetime:
    return utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def tokens_this_month(session: AsyncSession, company_id: int) -> int:
    q = select(func.coalesce(func.sum(UsageCost.tokens), 0)).where(
        UsageCost.company_id == company_id, UsageCost.created_at >= _month_start()
    )
    return int((await session.execute(q)).scalar_one())


async def posts_today(session: AsyncSession, company_id: int) -> int:
    day = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    q = select(func.count()).select_from(Post).where(Post.company_id == company_id, Post.created_at >= day)
    return int((await session.execute(q)).scalar_one())


async def check_token_budget(session: AsyncSession, company: Company) -> None:
    used = await tokens_this_month(session, company.id)
    if used >= company.monthly_token_limit:
        raise LimitExceeded(
            f"Месячный бюджет AI исчерпан ({used:,} из {company.monthly_token_limit:,} токенов). "
            "Администратор уведомлён."
        )


async def check_post_quota(session: AsyncSession, company: Company) -> None:
    n = await posts_today(session, company.id)
    if n >= company.daily_post_limit:
        raise LimitExceeded(f"Достигнут дневной лимит материалов ({company.daily_post_limit}). Продолжим завтра.")


async def first_budget_alert(session: AsyncSession, company_id: int) -> bool:
    """True, если об исчерпании бюджета в этом месяце ещё не сообщали администратору."""
    q = select(func.count()).select_from(AuditLog).where(
        AuditLog.company_id == company_id, AuditLog.action == "limit.tokens", AuditLog.created_at >= _month_start()
    )
    return (await session.execute(q)).scalar_one() == 0
