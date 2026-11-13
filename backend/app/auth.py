from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_session
from .models import User
from .security import AuthError, validate_init_data


@dataclass
class Ctx:
    user: User
    company_id: int | None

    @property
    def is_admin(self) -> bool:
        return self.user.role == "admin"

    # Роли: admin — оператор сервиса (настраивает компании, материалы не создаёт и не согласует);
    # approver — администратор компании (согласует, ставит задачи); member — сотрудник (ставит задачи).
    @property
    def can_approve(self) -> bool:
        return self.user.role == "approver"

    @property
    def can_create(self) -> bool:
        return self.user.role in ("approver", "member")

    def require_creator(self) -> None:
        if not self.can_create:
            raise HTTPException(403, "Оператор настраивает систему; материалы создают сотрудники компании")

    def require_company(self) -> int:
        if self.company_id is None:
            raise HTTPException(400, "Компания не выбрана (для администратора передайте X-Company-Id)")
        return self.company_id


async def get_ctx(
    authorization: str | None = Header(None),
    x_dev_user: str | None = Header(None),
    x_company_id: int | None = Header(None),
    session: AsyncSession = Depends(get_session),
) -> Ctx:
    """Определяет пользователя по подписанному initData Mini App (или X-Dev-User в dev-режиме)."""
    tg_id: int | None = None
    name = ""
    if settings.dev_auth_bypass and x_dev_user:
        tg_id = int(x_dev_user)
    elif authorization and authorization.startswith("tma "):
        try:
            data = validate_init_data(authorization[4:], settings.bot_token)
        except AuthError as e:
            raise HTTPException(401, f"initData: {e}")
        tg_id = int(data["id"])
        name = data.get("first_name", "")
    if tg_id is None:
        raise HTTPException(401, "Нет авторизации")

    user = (await session.execute(select(User).where(User.telegram_id == tg_id))).scalar_one_or_none()
    if user is None and tg_id in settings.admin_id_set:
        user = User(telegram_id=tg_id, name=name, role="admin")
        session.add(user)
        await session.commit()
    if user is None:
        raise HTTPException(403, "Пользователь не привязан к компании. Используйте ссылку-приглашение.")
    if tg_id in settings.admin_id_set and user.role != "admin":
        user.role = "admin"
        await session.commit()

    # Изоляция: обычный пользователь ВСЕГДА работает только в своей компании.
    company_id = x_company_id if user.role == "admin" else user.company_id
    return Ctx(user=user, company_id=company_id)


async def require_admin(ctx: Ctx = Depends(get_ctx)) -> Ctx:
    if not ctx.is_admin:
        raise HTTPException(403, "Только для администратора")
    return ctx
