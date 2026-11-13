"""Redis: кэш, ограничение частоты, распределённые блокировки, временное состояние диалога.

Без REDIS_URL работает встроенный in-memory Redis (fakeredis): код один и тот же в разработке, тестах и проде.
"""
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable

import redis.asyncio as aioredis

from .config import settings

log = logging.getLogger(__name__)
PREFIX = "aim:"

_client: aioredis.Redis | None = None


class RateLimited(Exception):
    pass


class LockBusy(Exception):
    pass


def get_redis() -> aioredis.Redis:
    global _client
    if _client is None:
        if settings.redis_url:
            _client = aioredis.from_url(settings.redis_url, decode_responses=True, health_check_interval=30)
        else:
            from fakeredis import FakeAsyncRedis

            _client = FakeAsyncRedis(decode_responses=True)
    return _client


def reset_client() -> None:
    """Сбрасывает клиент (тесты: у каждого теста свой event loop)."""
    global _client
    _client = None


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# ---------- кэш ----------

async def cached(key: str, loader: Callable[[], Awaitable[Any]], ttl: int | None = None) -> Any:
    """Значение из кэша или результат loader() (JSON-сериализуемый). Сбой Redis не ломает работу — идём в loader."""
    full = PREFIX + key
    try:
        raw = await get_redis().get(full)
        if raw is not None:
            return json.loads(raw)
    except Exception:
        log.warning("cache get %s failed", key, exc_info=True)
    value = await loader()
    try:
        await get_redis().set(full, json.dumps(value, ensure_ascii=False), ex=ttl or settings.cache_ttl_sec)
    except Exception:
        log.warning("cache set %s failed", key, exc_info=True)
    return value


async def invalidate(*keys: str) -> None:
    try:
        await get_redis().delete(*(PREFIX + k for k in keys))
    except Exception:
        log.warning("cache invalidate failed", exc_info=True)


# ---------- ограничение частоты (фиксированное окно) ----------

async def rate_limit(scope: str, limit: int, window_sec: int = 60) -> None:
    """Бросает RateLimited, если за окно уже было `limit` обращений. limit<=0 — без ограничения."""
    if limit <= 0:
        return
    key = f"{PREFIX}rl:{scope}"
    try:
        r = get_redis()
        n = await r.incr(key)
        if n == 1:
            await r.expire(key, window_sec)
    except Exception:
        log.warning("rate_limit %s: Redis недоступен, ограничение пропущено", scope, exc_info=True)
        return
    if n > limit:
        raise RateLimited(f"Слишком много запросов, попробуйте через минуту (лимит {limit} в минуту).")


# ---------- распределённые блокировки ----------

@asynccontextmanager
async def lock(name: str, ttl_sec: int = 120):
    """Не даёт двум экземплярам приложения одновременно обрабатывать одну сущность. LockBusy — уже занято."""
    lk = get_redis().lock(f"{PREFIX}lock:{name}", timeout=ttl_sec, blocking=False)
    if not await lk.acquire():
        raise LockBusy(name)
    try:
        yield
    finally:
        try:
            await lk.release()
        except Exception:  # истёк TTL — блокировку уже забрал другой
            log.warning("lock %s не освобождена", name)


# ---------- временное состояние диалога ----------

async def set_state(user_id: int, value: str) -> None:
    await get_redis().set(f"{PREFIX}state:{user_id}", value, ex=settings.dialog_state_ttl_sec)


async def get_state(user_id: int) -> str:
    return await get_redis().get(f"{PREFIX}state:{user_id}") or ""


async def clear_state(user_id: int) -> None:
    await get_redis().delete(f"{PREFIX}state:{user_id}")
