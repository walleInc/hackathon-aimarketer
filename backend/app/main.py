import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from aiogram.types import Update
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from . import tg
from .config import settings
from .db import init_db
from .routers import admin, client
from .scheduler import create_scheduler

logging.basicConfig(level=logging.INFO)
FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    Path(settings.media_dir).mkdir(parents=True, exist_ok=True)
    scheduler = create_scheduler()
    scheduler.start()
    polling: asyncio.Task | None = None
    if tg.bot:
        if settings.public_url:
            await tg.bot.set_webhook(
                f"{settings.public_url.rstrip('/')}/webhook/{settings.webhook_secret}",
                allowed_updates=["message", "callback_query"],
            )
        else:  # локальная разработка без публичного адреса
            await tg.bot.delete_webhook()
            polling = asyncio.create_task(tg.dp.start_polling(tg.bot, handle_signals=False))
    yield
    scheduler.shutdown(wait=False)
    if polling:
        polling.cancel()
    if tg.bot:
        await tg.bot.session.close()


app = FastAPI(title="AI-маркетолог", lifespan=lifespan)
app.include_router(client.router)
app.include_router(admin.router)


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
