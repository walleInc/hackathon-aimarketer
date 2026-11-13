import os
import tempfile

# Настройки должны быть заданы ДО импорта приложения
_tmp = tempfile.mkdtemp()
os.environ.update(
    DATABASE_URL=f"sqlite+aiosqlite:///{_tmp}/test.db",
    DEV_AUTH_BYPASS="true",
    ADMIN_IDS="1",
    LLM_PROVIDER="stub",
    BOT_TOKEN="",
    MEDIA_DIR=f"{_tmp}/media",
    REDIS_URL="",  # тесты: встроенный Redis и задачи в процессе
    S3_BUCKET="",
    S3_ACCESS_KEY_ID="",
    S3_SECRET_ACCESS_KEY="",
)

import httpx
import pytest
import pytest_asyncio

from app import cache, platforms
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Company, SocialAccount, User


class FakePlatform:
    def __init__(self):
        self.published: list[str] = []

    async def publish(self, account, text, image_url=""):
        self.published.append(text)
        return f"ext-{len(self.published)}"


@pytest_asyncio.fixture
async def env():
    """Две компании: A (пользователи 100 approver, 101 member) и B (пользователь 200 approver)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    cache.reset_client()  # новый event loop — новый клиент; пустой кэш/лимиты/блокировки
    fake = FakePlatform()
    platforms.REGISTRY["telegram"] = fake
    async with SessionLocal() as s:
        a, b = Company(name="A"), Company(name="B")
        s.add_all([a, b])
        await s.commit()
        s.add_all(
            [
                User(telegram_id=100, role="approver", company_id=a.id),
                User(telegram_id=101, role="member", company_id=a.id),
                User(telegram_id=200, role="approver", company_id=b.id),
                SocialAccount(company_id=a.id, platform="telegram", channel_id="@a"),
                SocialAccount(company_id=b.id, platform="telegram", channel_id="@b"),
            ]
        )
        await s.commit()
        ids = {"a": a.id, "b": b.id}
    return {"fake": fake, **ids}


@pytest_asyncio.fixture
async def client(env):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def as_user(tg_id: int) -> dict:
    return {"X-Dev-User": str(tg_id)}
