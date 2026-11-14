"""Isolated local server for browser integration tests. Never reads production credentials."""
import asyncio
import os
import tempfile

_dir = tempfile.mkdtemp(prefix="aimarketer-browser-")
os.environ.update(DATABASE_URL=f"sqlite+aiosqlite:///{_dir}/test.db", MEDIA_DIR=f"{_dir}/media",
                  DEV_AUTH_BYPASS="true", ADMIN_IDS="1", BOT_TOKEN="", REDIS_URL="", PUBLIC_URL="",
                  LLM_PROVIDER="stub", TAVILY_API_KEY="", S3_BUCKET="", S3_ACCESS_KEY_ID="", S3_SECRET_ACCESS_KEY="",
                  TELEGRAM_API_ID="0", TELEGRAM_API_HASH="", AI_IMAGES="false")

from app.db import SessionLocal, init_db, utcnow
from app.models import Company, KnowledgeDoc, MarketingSettings, Post, SocialAccount, User
from app.post_analytics import record_metrics
from datetime import timedelta


async def seed():
    await init_db()
    async with SessionLocal() as session:
        a, b = Company(name="САЛАВАТСТЕКЛО", description="Производство стекла для строительства"), Company(name="Другая компания")
        session.add_all([a, b])
        await session.flush()
        session.add_all([User(telegram_id=100, role="approver", company_id=a.id),
                         User(telegram_id=101, role="member", company_id=a.id),
                         User(telegram_id=200, role="approver", company_id=b.id),
                         MarketingSettings(company_id=a.id, niche="Стекло для строительства", geography="Россия", goals="Развивать экспертный контент"),
                         KnowledgeDoc(company_id=a.id, title="О компании", content="Компания производит стекло для строительства."),
                         SocialAccount(company_id=a.id, platform="telegram", channel_id="-100123")])
        for i in range(3):
            post = Post(company_id=a.id, text=f"Публикация о применении стекла #{i + 1}", status="published", external_id=str(i + 1), published_channel_id="-100123", published_at=utcnow() - timedelta(days=2))
            session.add(post)
            await session.flush()
            await record_metrics(session, post, {"views": 100 * (i + 1), "reactions": i + 1}, utcnow())
        await session.commit()


if __name__ == "__main__":
    import uvicorn
    asyncio.run(seed())
    uvicorn.run("app.main:app", host="127.0.0.1", port=8011)
