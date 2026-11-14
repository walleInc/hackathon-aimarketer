"""Telegram user login is available only to the company's approver. Secrets never leave the server."""
import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import cache, services
from ..auth import Ctx, get_ctx
from ..config import settings
from ..db import get_session, utcnow
from ..models import SocialAccount, TelegramConnection
from ..security import decrypt, encrypt
from ..telegram_analytics import configured, telegram_client, connection_session
from ..jobs import PermanentFailure

router = APIRouter(prefix="/api/telegram-analytics", tags=["telegram-analytics"])


def manager(ctx):
    if ctx.user.role != "approver":
        raise HTTPException(403, "Telegram подключает администратор компании")


@asynccontextmanager
async def auth_lock(cid):
    key, token = f"{cache.PREFIX}tg-auth:{cid}", uuid.uuid4().hex
    redis = cache.get_redis()
    if not await redis.set(key, token, nx=True, ex=90):
        raise HTTPException(409, "Подключение уже выполняется")
    try:
        async with asyncio.timeout(60):
            yield
    except TimeoutError:
        raise HTTPException(504, "Telegram не ответил вовремя. Повторите позже")
    finally:
        await redis.eval("if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0", 1, key, token)


async def login_rate_limit(key: str, limit: int):
    try:
        await cache.rate_limit(key, limit)
    except cache.RateLimited as exc:
        raise HTTPException(429, str(exc))


async def authorized_session(session, cid):
    try:
        return await connection_session(session, cid)
    except PermanentFailure as exc:
        raise HTTPException(422, str(exc))


@router.get("")
async def status(ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    cid = ctx.require_company()
    row = await session.get(TelegramConnection, cid)
    channels = (await session.execute(select(SocialAccount).where(SocialAccount.company_id == cid, SocialAccount.platform == "telegram", SocialAccount.active.is_(True)))).scalars()
    return {"configured": configured(), "web_search_configured": bool(settings.tavily_api_key),
            "connected": bool(row and row.session_encrypted), "can_connect": ctx.user.role == "approver",
            "channels": [{"id": c.id, "channel_id": c.channel_id} for c in channels]}


class PhoneIn(BaseModel):
    phone: str = Field(pattern=r"^\+[1-9]\d{6,14}$")


class CodeIn(BaseModel):
    code: str = Field(default="", max_length=20)
    password: str = Field(default="", max_length=256)


@router.post("/connect")
async def connect(body: PhoneIn, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    manager(ctx)
    cid = ctx.require_company()
    if not configured():
        raise HTTPException(422, "Оператору нужно настроить TELEGRAM_API_ID и TELEGRAM_API_HASH")
    await login_rate_limit(f"tg-login:{cid}", 3)
    async with auth_lock(cid):
        try:
            async with telegram_client() as client:
                sent = await client.send_code_request(body.phone)
                pending = {"session": client.session.save(), "phone": body.phone, "phone_code_hash": sent.phone_code_hash}
            row = await session.get(TelegramConnection, cid)
            if row is None:
                row = TelegramConnection(company_id=cid)
                session.add(row)
            row.pending_encrypted, row.auth_owner, row.updated_at = encrypt(json.dumps(pending)), ctx.user.id, utcnow()
            await session.commit()
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(502, "Telegram не отправил код. Проверьте номер и повторите позже")
    return {"step": "code"}


@router.post("/verify")
async def verify(body: CodeIn, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    from telethon.errors import SessionPasswordNeededError
    manager(ctx)
    cid = ctx.require_company()
    await login_rate_limit(f"tg-verify:{cid}", 5)
    async with auth_lock(cid):
        row = await session.get(TelegramConnection, cid)
        if not row or not row.pending_encrypted or row.auth_owner != ctx.user.id or row.updated_at < utcnow() - timedelta(minutes=10):
            raise HTTPException(422, "Запрос кода истёк. Начните подключение заново")
        pending = json.loads(decrypt(row.pending_encrypted))
        try:
            async with telegram_client(pending["session"]) as client:
                try:
                    if body.password:
                        if not pending.get("needs_password"):
                            raise HTTPException(422, "Сначала введите код")
                        await client.sign_in(password=body.password)
                    else:
                        await client.sign_in(pending["phone"], code=body.code, phone_code_hash=pending["phone_code_hash"])
                except SessionPasswordNeededError:
                    pending["session"], pending["needs_password"] = client.session.save(), True
                    row.pending_encrypted = encrypt(json.dumps(pending))
                    await session.commit()
                    return {"step": "password"}
                row.session_encrypted = encrypt(client.session.save())
                row.pending_encrypted, row.auth_owner, row.updated_at = "", None, utcnow()
                await session.commit()
            await services.audit(session, cid, ctx.user.id, "telegram.connected", "analytics session")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, "Не удалось подтвердить вход. Проверьте код или пароль; при необходимости запросите новый код")
    return {"step": "connected"}


@router.delete("")
async def disconnect(ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    manager(ctx)
    cid = ctx.require_company()
    async with auth_lock(cid):
        row = await session.get(TelegramConnection, cid)
        if row:
            if row.session_encrypted:
                try:
                    async with telegram_client(decrypt(row.session_encrypted)) as client:
                        await client.log_out()
                except Exception:
                    raise HTTPException(502, "Не удалось отозвать сессию Telegram; повторите отключение")
            await session.delete(row)
            await session.commit()
            await services.audit(session, cid, ctx.user.id, "telegram.disconnected", "analytics session revoked")
    return {"ok": True}


@router.get("/available-channels")
async def available_channels(ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    from telethon import utils
    manager(ctx)
    saved = await authorized_session(session, ctx.require_company())
    channels = []
    try:
        async with asyncio.timeout(60), telegram_client(saved) as client:
            async for dialog in client.iter_dialogs(limit=500):
                entity = dialog.entity
                if getattr(entity, "broadcast", False):
                    channels.append({"channel_id": str(utils.get_peer_id(entity)), "title": dialog.title})
    except Exception:
        raise HTTPException(502, "Не удалось загрузить каналы; проверьте подключение Telegram")
    return channels


class ChannelIn(BaseModel):
    channel_id: str = Field(pattern=r"^-100\d+$")


@router.post("/channels")
async def attach_channel(body: ChannelIn, ctx: Ctx = Depends(get_ctx), session: AsyncSession = Depends(get_session)):
    from ..telegram_analytics import resolve_channel
    manager(ctx)
    cid = ctx.require_company()
    saved = await authorized_session(session, cid)
    try:
        async with asyncio.timeout(60), telegram_client(saved) as client:
            await resolve_channel(client, body.channel_id)
    except Exception:
        raise HTTPException(422, "Канал недоступен подключённому аккаунту")
    row = (await session.execute(select(SocialAccount).where(SocialAccount.company_id == cid, SocialAccount.channel_id == body.channel_id, SocialAccount.platform == "telegram"))).scalars().first()
    if row is None:
        row = SocialAccount(company_id=cid, platform="telegram", channel_id=body.channel_id, analytics_only=True)
        session.add(row)
    row.active = True
    await session.commit()
    return {"id": row.id}
