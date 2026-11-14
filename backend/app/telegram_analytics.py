"""Read-only Telegram user sessions for channel metrics; no message sending permissions are used here."""
import json
from contextlib import asynccontextmanager
from datetime import timedelta, timezone

from sqlalchemy import select

from .config import settings
from .db import utcnow
from .jobs import PermanentFailure
from .models import SocialAccount, Task, TaskRun, TelegramConnection
from .security import decrypt


def configured():
    return bool(settings.telegram_api_id and settings.telegram_api_hash)


@asynccontextmanager
async def telegram_client(saved: str = ""):
    if not configured():
        raise PermanentFailure("Не настроены TELEGRAM_API_ID и TELEGRAM_API_HASH")
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    client = TelegramClient(StringSession(saved), settings.telegram_api_id, settings.telegram_api_hash,
                            receive_updates=False, request_retries=1, connection_retries=1,
                            flood_sleep_threshold=0, timeout=15)
    try:
        await client.connect()
        yield client
    finally:
        await client.disconnect()


async def connection_session(session, company_id: int):
    connection = await session.get(TelegramConnection, company_id)
    if connection is None or not connection.session_encrypted:
        raise PermanentFailure("Администратору компании нужно подключить Telegram-аккаунт")
    return decrypt(connection.session_encrypted)


async def resolve_channel(client, channel_id: str):
    from telethon import utils
    if channel_id.startswith("@"):
        entity = await client.get_entity(channel_id)
    else:
        entity = None
        async for dialog in client.iter_dialogs(limit=500):
            if str(utils.get_peer_id(dialog.entity)) == channel_id:
                entity = dialog.entity
                break
    if entity is None or not getattr(entity, "broadcast", False):
        raise PermanentFailure("Канал недоступен подключённому аккаунту или не является Telegram-каналом")
    return entity


async def collect_metrics(session, task):
    from telethon import functions
    from telethon.errors import RPCError
    account = await session.get(SocialAccount, task.channel_id)
    if account is None or account.company_id != task.company_id or not account.active:
        raise PermanentFailure("Канал отключён")
    saved = await connection_session(session, task.company_id)
    async with telegram_client(saved) as client:
        if not await client.is_user_authorized():
            raise PermanentFailure("Telegram-сессия истекла; подключите аккаунт повторно")
        entity = await resolve_channel(client, account.channel_id)
        full = await client(functions.channels.GetFullChannelRequest(entity))
        now = utcnow()
        since = (now - timedelta(days=7)).replace(tzinfo=timezone.utc)
        messages = []
        scanned, truncated = 0, False
        async for message in client.iter_messages(entity, limit=2000):
            scanned += 1
            if message.date < since:
                break
            if message.action:
                continue
            messages.append({"id": message.id, "date": message.date.isoformat(), "views": message.views,
                             "forwards": message.forwards,
                             "text": (getattr(message, "message", "") or "")[:10000],
                             "format": "video" if getattr(message, "video", None) else "photo" if getattr(message, "photo", None) else "text",
                             "comments": getattr(getattr(message, "replies", None), "replies", None),
                             "reactions": sum(r.count for r in message.reactions.results) if message.reactions else 0})
        else:
            truncated = scanned == 2000
        views = sum(m["views"] for m in messages if m["views"] is not None)
        reactions = sum(m["reactions"] for m in messages)
        forwards = sum(m["forwards"] for m in messages if m["forwards"] is not None)
        metrics = {"channel": account.channel_id, "collected_at": now.isoformat() + "Z", "period_days": 7,
                   "subscribers": getattr(full.full_chat, "participants_count", None),
                   "posts": len(messages), "views": views if all(m["views"] is not None for m in messages) else None,
                   "reactions": reactions, "forwards": forwards if all(m["forwards"] is not None for m in messages) else None,
                   "engagement_percent": round((reactions + forwards) / views * 100, 2) if views and all(m["views"] is not None and m["forwards"] is not None for m in messages) else None,
                   "messages": messages, "truncated": truncated, "full_statistics": None}
        if getattr(entity, "id", None):
            from telethon import utils
            metrics["resolved_channel"] = str(utils.get_peer_id(entity))
        if getattr(full.full_chat, "can_view_stats", False):
            try:
                stats = await client.get_stats(entity)
                metrics["full_statistics"] = {
                    "period": {"from": stats.period.min_date.isoformat(), "to": stats.period.max_date.isoformat()},
                    **{key: {"current": getattr(stats, key).current, "previous": getattr(stats, key).previous}
                       for key in ("followers", "views_per_post", "shares_per_post", "reactions_per_post") if getattr(stats, key, None) is not None},
                }
            except RPCError:
                metrics["full_statistics_unavailable"] = "Telegram не предоставил полную статистику; используются счётчики публикаций"
        else:
            metrics["full_statistics_unavailable"] = "Полная статистика недоступна этому аккаунту или каналу"
    previous = (await session.execute(select(TaskRun).join(Task).where(
        Task.company_id == task.company_id, Task.channel_id == task.channel_id,
        Task.kind.in_(["statistics", "sync"]), TaskRun.status == "succeeded",
    ).order_by(TaskRun.id.desc()).limit(1))).scalar_one_or_none()
    if previous:
        old = json.loads(previous.metrics)
        metrics["previous_snapshot_at"] = old.get("collected_at")
        before, after = old.get("subscribers"), metrics["subscribers"]
        metrics["subscribers_change"] = after - before if before is not None and after is not None else None
        metrics["change_since_previous_snapshot"] = {
            key: metrics[key] - old[key] if metrics.get(key) is not None and old.get(key) is not None else None
            for key in ("subscribers", "views", "reactions", "forwards")
        }
        metrics["comparison_note"] = "Снимки скользящего окна 7 дней могут перекрываться; это не сравнение независимых недель"
    else:
        metrics["subscribers_change"] = None
    return metrics
