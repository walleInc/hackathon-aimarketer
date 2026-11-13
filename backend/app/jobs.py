"""Очереди задач на BullMQ (Redis): повторы, отложенный запуск, ограничение параллелизма, изоляция организаций.

Без REDIS_URL (разработка, тесты) задачи выполняются сразу, в том же процессе, одной попыткой.
Обработчики регистрируются декоратором @handler в app/handlers.py.
"""
import logging
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from bullmq import DelayedError, Queue, UnrecoverableError, Worker

from . import cache
from .config import settings

log = logging.getLogger(__name__)

# очередь -> (параллелизм воркера, для чего нужна)
QUEUES: dict[str, int] = {
    "document-processing": 2,   # извлечение текста из PDF/DOCX
    "ai-generation": 0,         # посты, картинки, контент-планы; параллелизм = settings.ai_concurrency
    "publishing": 3,            # публикация в Telegram / VK / MAX
    "scheduled-tasks": 1,       # тик планировщика
    "analytics": 1,             # сбор статистики
    "notifications": 5,         # уведомления в Telegram
    "moderation": 2,            # анализ комментариев и входящих сообщений
}
REMOVE_ON_COMPLETE = {"age": 3600, "count": 1000}
REMOVE_ON_FAIL = {"age": 7 * 86400, "count": 5000}


@dataclass
class JobCtx:
    attempt: int = 1
    max_attempts: int = 1

    @property
    def is_last(self) -> bool:
        return self.attempt >= self.max_attempts


class RetryLater(Exception):
    """Вернуть задачу в очередь с задержкой (не считается неудачной попыткой)."""

    def __init__(self, delay_ms: int):
        self.delay_ms = max(1000, int(delay_ms))


class PermanentFailure(Exception):
    """Повторять бессмысленно."""


Handler = Callable[[dict, JobCtx], Awaitable[Any]]
_handlers: dict[tuple[str, str], Handler] = {}
_queues: dict[str, Queue] = {}
_workers: list[Worker] = []


def handler(queue: str, name: str):
    def deco(fn: Handler) -> Handler:
        _handlers[(queue, name)] = fn
        return fn

    return deco


def _load_handlers() -> None:
    from . import handlers  # noqa: F401  (регистрация обработчиков)


def queue_mode() -> str:
    return "bullmq" if settings.redis_url else "inline"


def _queue(name: str) -> Queue:
    if name not in QUEUES:
        raise ValueError(f"неизвестная очередь {name}")
    if name not in _queues:
        _queues[name] = Queue(name, {"connection": settings.redis_url})
    return _queues[name]


async def _run(queue: str, name: str, data: dict, ctx: JobCtx) -> Any:
    _load_handlers()
    fn = _handlers.get((queue, name))
    if fn is None:
        raise PermanentFailure(f"нет обработчика {queue}/{name}")
    return await fn(data, ctx)


async def enqueue(
    queue: str, name: str, data: dict, *, delay_ms: int = 0, attempts: int = 3, backoff_ms: int = 5000,
    dedup_id: str | None = None, dedup_ttl_ms: int = 120_000,
) -> str | None:
    """Ставит задачу в очередь. Возвращает id задачи (None — отложенная задача в inline-режиме или дубль)."""
    if queue_mode() == "inline":
        if delay_ms > 0:
            return None  # отложенное выполнение в inline-режиме берёт на себя тик планировщика
        try:
            await _run(queue, name, data, JobCtx())
        except Exception:
            log.exception("job %s/%s failed", queue, name)
        return "inline"
    opts: dict[str, Any] = {
        "attempts": attempts, "backoff": {"type": "exponential", "delay": backoff_ms},
        "removeOnComplete": REMOVE_ON_COMPLETE, "removeOnFail": REMOVE_ON_FAIL,
    }
    if delay_ms > 0:
        opts["delay"] = int(delay_ms)
    if dedup_id:
        opts["deduplication"] = {"id": dedup_id, "ttl": dedup_ttl_ms}
    try:
        job = await _queue(queue).add(name, data, opts)
        return job.id
    except Exception:
        log.exception("не удалось поставить задачу %s/%s в очередь", queue, name)
        if delay_ms > 0:
            return None  # подхватит тик планировщика
        try:  # Redis недоступен: не теряем задачу, выполняем сразу
            await _run(queue, name, data, JobCtx())
        except Exception:
            log.exception("job %s/%s failed", queue, name)
        return "fallback"


@asynccontextmanager
async def org_slot(queue: str, company_id: int | None):
    """Изоляция организаций: не более N одновременных задач очереди на одну организацию."""
    if company_id is None or settings.ai_org_concurrency <= 0 or queue_mode() == "inline":
        yield
        return
    r, key = cache.get_redis(), f"{cache.PREFIX}slots:{queue}:{company_id}"
    n = await r.incr(key)
    await r.expire(key, 900)  # страховка: слот не «залипнет» при падении воркера
    try:
        if n > settings.ai_org_concurrency:
            raise RetryLater(5000)
        yield
    finally:
        await r.decr(key)


def _make_processor(queue: str):
    async def process(job, token):
        ctx = JobCtx(attempt=job.attemptsMade + 1, max_attempts=max(job.attempts or 1, 1))
        try:
            return await _run(queue, job.name, job.data, ctx)
        except RetryLater as e:
            await job.moveToDelayed(int(time.time() * 1000) + e.delay_ms, token)
            raise DelayedError()
        except PermanentFailure as e:
            raise UnrecoverableError(str(e))

    return process


async def start_workers() -> None:
    """Запускает воркеры всех очередей и периодические задачи. Только в режиме bullmq."""
    if queue_mode() != "bullmq" or _workers:
        return
    _load_handlers()
    for name, conc in QUEUES.items():
        concurrency = conc or settings.ai_concurrency
        _workers.append(Worker(name, _make_processor(name), {"connection": settings.redis_url, "concurrency": concurrency}))
    # периодические задачи: единый планировщик на все экземпляры приложения (дубли исключены самим BullMQ)
    sched = {"removeOnComplete": True, "removeOnFail": 100}
    await _queue("scheduled-tasks").upsertJobScheduler(
        "tick", {"every": settings.scheduler_interval_sec * 1000}, "tick", {}, sched
    )
    await _queue("analytics").upsertJobScheduler("collect", {"every": 3600 * 1000}, "collect", {}, sched)
    log.info("воркеры очередей запущены: %s", ", ".join(QUEUES))


async def stop_workers() -> None:
    for w in _workers:
        await w.close()
    _workers.clear()
    for q in _queues.values():
        await q.close()
    _queues.clear()


async def stats() -> dict[str, dict[str, int]]:
    """Состояния задач по очередям: waiting, active, completed, failed, delayed."""
    if queue_mode() != "bullmq":
        return {}
    out = {}
    for name in QUEUES:
        c = await _queue(name).getJobCounts("waiting", "active", "completed", "failed", "delayed")
        out[name] = {k: int(c.get(k, 0)) for k in ("waiting", "active", "completed", "failed", "delayed")}
    return out
