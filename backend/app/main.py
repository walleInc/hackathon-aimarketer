import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from . import cache, events, jobs, tg
from .config import settings
from .db import init_db
from .routers import admin, analytics, client
from .scheduler import create_scheduler

logging.basicConfig(level=logging.INFO)
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


log = logging.getLogger(__name__)


async def _set_webhook_with_retries(attempts: int = 20) -> None:
    url = f"{settings.public_url.rstrip('/')}/webhook/{settings.webhook_secret}"
    for attempt in range(1, attempts + 1):
        try:
            await tg.bot.set_webhook(url, allowed_updates=["message", "callback_query", "message_reaction_count"])
            log.info("webhook установлен (попытка %d)", attempt)
            return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("webhook не установлен (попытка %d/%d): %s", attempt, attempts, e)
            await asyncio.sleep(min(60, 5 * attempt))
    log.error("webhook так и не установлен — бот не будет получать сообщения")


async def _run_polling() -> None:
    """Long polling: сервер сам забирает сообщения, входящий доступ из Telegram не нужен."""
    while True:
        try:
            await tg.bot.delete_webhook()  # webhook и polling взаимоисключающи; очередь не сбрасываем
            log.info("бот запущен в режиме long polling")
            await tg.dp.start_polling(tg.bot, handle_signals=False, allowed_updates=["message", "callback_query", "message_reaction_count"])
            return
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("polling не запущен, повтор через 10 с: %s", e)
            await asyncio.sleep(10)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    Path(settings.media_dir).mkdir(parents=True, exist_ok=True)
    scheduler = None
    if jobs.queue_mode() == "bullmq":
        if settings.run_workers:  # очереди BullMQ: воркеры и периодические задачи
            await jobs.start_workers()
    else:  # без Redis: планировщик в процессе, задачи выполняются сразу
        scheduler = create_scheduler()
        scheduler.start()
    pubsub = asyncio.create_task(events.listen())  # события между экземплярами приложения
    background: asyncio.Task | None = None
    if tg.bot:
        if settings.public_url and settings.bot_mode == "webhook":
            # Telegram может быть временно недоступен: сервис всё равно стартует, webhook ставится с повторами
            background = asyncio.create_task(_set_webhook_with_retries())
        else:  # локальная разработка или сервер, недоступный для webhook
            background = asyncio.create_task(_run_polling())
    yield
    if scheduler:
        scheduler.shutdown(wait=False)
    pubsub.cancel()
    await jobs.stop_workers()
    await cache.close()
    if background:
        background.cancel()
    if tg.bot:
        await tg.bot.session.close()


app = FastAPI(title="AI-маркетолог", lifespan=lifespan)
app.include_router(client.router)
app.include_router(admin.router)
app.include_router(analytics.router)


@app.get("/health")
async def health():
    return {"ok": True}


@app.post("/webhook/{secret}")
async def webhook(secret: str, request: Request):
    if secret != settings.webhook_secret or tg.bot is None:
        raise HTTPException(404)
    await tg.dp.feed_update(tg.bot, Update.model_validate(await request.json(), context={"bot": tg.bot}))
    return {"ok": True}


Path(settings.media_dir).mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")
# Mini App (сборка Vite) отдаётся тем же сервисом: один домен для API, бота и фронтенда
if FRONTEND_DIST.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIST, html=True), name="frontend")
