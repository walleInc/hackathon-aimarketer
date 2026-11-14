"""Optional real-PostgreSQL migration and API smoke test (uses an isolated temporary schema)."""
import os
import uuid
from datetime import date

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import cache, content_plans, db
from app.main import app
from app.models import Company, ContentPlanItem, Post, User
from tests.conftest import as_user


@pytest.mark.skipif(not os.getenv('CONTENT_PLAN_TEST_DATABASE_URL'), reason='Set CONTENT_PLAN_TEST_DATABASE_URL for PostgreSQL integration')
async def test_postgres_migration_and_content_plan_api(monkeypatch):
    url = os.environ['CONTENT_PLAN_TEST_DATABASE_URL']
    admin_engine = create_async_engine(url)
    schema = 'content_plan_test_' + uuid.uuid4().hex
    async with admin_engine.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    pg_engine = create_async_engine(url, connect_args={'server_settings': {'search_path': schema}})
    factory = async_sessionmaker(pg_engine, expire_on_commit=False)
    try:
        async with pg_engine.begin() as conn:
            await conn.execute(text('CREATE TABLE posts (id SERIAL PRIMARY KEY, company_id INTEGER, platform VARCHAR(20), text TEXT, status VARCHAR(20), created_at TIMESTAMP)'))
            await conn.execute(text("INSERT INTO posts (id, company_id, platform, text, status) VALUES (999, 1, 'telegram', 'Legacy post', 'published')"))
        monkeypatch.setattr(db, 'engine', pg_engine)
        monkeypatch.setattr(db, 'SessionLocal', factory)
        monkeypatch.setattr(content_plans, 'SessionLocal', factory)
        cache.reset_client()
        await db.init_db()
        await db.init_db()
        async with factory() as session:
            company = Company(name='PostgreSQL company')
            session.add(company); await session.flush()
            session.add(User(company_id=company.id, telegram_id=555, role='member'))
            await session.commit()
            legacy = await session.get(Post, 999)
            assert legacy.text == 'Legacy post' and legacy.content_plan_item_id is None
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.post('/api/content-plans', headers=as_user(555), json={
                'title': 'Postgres plan', 'start_date': '2030-01-01', 'end_date': '2030-01-01', 'posts_per_day': 2})
            assert response.status_code == 202, response.text
            plan = (await client.get(f'/api/content-plans/{response.json()["id"]}', headers=as_user(555))).json()
            assert plan['status'] == 'ready' and len(plan['items']) == 2
            item = plan['items'][0]
            generated = await client.post('/api/posts/generate', headers=as_user(555), json={'prompt': 'Пост из PostgreSQL', 'content_plan_item_id': item['id']})
            assert generated.status_code == 200, generated.text
            assert generated.json()['status'] == 'pending_approval'
        async with factory() as session:
            stored = (await session.execute(select(ContentPlanItem).order_by(ContentPlanItem.id))).scalars().all()
            assert len(stored) == 2 and stored[0].planned_date == date(2030, 1, 1)
            post = await session.get(Post, generated.json()['id'])
            assert post.content_plan_item_id == item['id'] and post.content_plan_prompt == 'Пост из PostgreSQL'
    finally:
        await pg_engine.dispose()
        async with admin_engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin_engine.dispose()
