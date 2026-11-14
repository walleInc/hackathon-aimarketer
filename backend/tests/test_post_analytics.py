from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app import post_analytics, services, tg
from app.db import SessionLocal, utcnow
from app.llm.base import LLMResult
from app.models import Company, Post, UsageCost
from tests.conftest import as_user


async def published(cid, age=2, channel='-100123', external='12', dated=True, status='published'):
    async with SessionLocal() as session:
        post = Post(company_id=cid, text='Полезный пост', status=status, published_at=utcnow() - timedelta(days=age) if dated else None, published_channel_id=channel, external_id=external)
        session.add(post)
        await session.commit()
        return post.id


async def dashboard(client, user=100, days=30, **headers):
    response = await client.get(f'/api/analytics/posts?days={days}', headers={**as_user(user), **headers})
    assert response.status_code == 200, response.text
    return response.json()


async def save(client, pid, values, user=100):
    return await client.put(f'/api/posts/{pid}/metrics', headers=as_user(user), json=values)


async def test_unknown_zero_and_partial_update(client, env):
    pid = await published(env['a'])
    assert (await dashboard(client))['summary']['views'] == {'total': None, 'measured_posts': 0}
    assert (await save(client, pid, {'views': 0})).status_code == 200
    assert (await save(client, pid, {'reactions': 0})).status_code == 200
    data = await dashboard(client)
    assert data['summary']['views'] == {'total': 0, 'measured_posts': 1}
    assert data['summary']['comments']['total'] is None
    assert data['posts'][0]['reaction_rate'] is None
    assert data['posts'][0]['metrics']['views']['source'] == 'manual'


async def test_isolation_and_permissions(client, env):
    own = await published(env['a'])
    other = await published(env['b'])
    assert [row['id'] for row in (await dashboard(client, **{'X-Company-Id': str(env['b'])}))['posts']] == [own]
    assert (await save(client, other, {'views': 12})).status_code == 404
    for user in [101, 1]:
        assert (await save(client, own, {'views': 12}, user=user)).status_code == 403
    assert (await dashboard(client, user=1, **{'X-Company-Id': str(env['b'])}))['posts'][0]['id'] == other


@pytest.mark.parametrize('values', [{}, {'views': None}, {'views': -1}, {'views': 1.2}, {'views': True}, {'views': 2_000_000_001}, {'views': 1, 'observed_at': '2026-01-01T12:00:00'}])
async def test_invalid_measurements(client, env, values):
    assert (await save(client, await published(env['a']), values)).status_code == 422


async def test_unpublished_and_invalid_dates(client, env):
    draft = await published(env['a'], status='draft')
    pid = await published(env['a'])
    for target, values in [(draft, {'views': 1}), (pid, {'views': 1, 'observed_at': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}), (pid, {'views': 1, 'observed_at': (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()})]:
        assert (await save(client, target, values)).status_code == 422
    assert (await dashboard(client))['summary']['views']['total'] is None


async def test_period_and_legacy_dates(client, env):
    recent = await published(env['a'])
    old = await published(env['a'], age=50)
    legacy = await published(env['a'], dated=False)
    await published(env['a'], status='pending_approval')
    data = await dashboard(client, days=7)
    assert [row['id'] for row in data['posts']] == [recent]
    assert data['unknown_publication_dates'] == 1
    assert {row['id'] for row in (await dashboard(client, days=0))['posts']} == {recent, old, legacy}
    assert (await client.get('/api/analytics/posts?days=5', headers=as_user(100))).status_code == 422


async def test_telegram_absolute_idempotent_ordered_and_scoped(client, env):
    own = await published(env['a'], external='22')
    await published(env['b'], channel='-100999', external='22')
    now = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(seconds=5)
    event = SimpleNamespace(chat=SimpleNamespace(id=-100123), message_id=22, date=now, reactions=[SimpleNamespace(total_count=7), SimpleNamespace(total_count=3)])
    await tg.on_reaction_count(event)
    await tg.on_reaction_count(event)
    event.date -= timedelta(seconds=2)
    event.reactions = [SimpleNamespace(total_count=20)]
    await tg.on_reaction_count(event)
    assert (await dashboard(client))['posts'][0]['metrics']['reactions']['value'] == 10
    assert (await dashboard(client, user=200))['posts'][0]['metrics']['reactions']['value'] is None
    event.date = now + timedelta(seconds=1)
    event.reactions = []
    await tg.on_reaction_count(event)
    assert (await dashboard(client))['posts'][0]['metrics']['reactions']['value'] == 0
    assert (await save(client, own, {'views': 100, 'reactions': 9, 'observed_at': (now - timedelta(seconds=1)).isoformat()})).status_code == 422
    assert (await dashboard(client))['summary']['views']['total'] is None  # вся устаревшая запись откатилась


async def test_rates_and_recommendations(client, env):
    ids = [await published(env['a'], external=str(i)) for i in range(4)]
    for pid, reactions in zip(ids[:3], [1, 5, 10]):
        assert (await save(client, pid, {'views': 100, 'reactions': reactions})).status_code == 200
    async with SessionLocal() as session:
        post = await session.get(Post, ids[3])
        post.published_channel_id = '-100456'
        await session.commit()
        await post_analytics.record_metrics(session, post, {'views': 100}, utcnow() - timedelta(days=1, seconds=1))
        await post_analytics.record_metrics(session, post, {'reactions': 90}, utcnow())
        await session.commit()
    data = await dashboard(client)
    assert data['summary']['reaction_rate'] == 5.33
    assert data['summary']['rate_posts'] == 3
    assert next(row for row in data['posts'] if row['id'] == ids[3])['reaction_rate'] is None
    rec = next(item for item in data['recommendations'] if item['post_ids'])
    assert rec['post_ids'] == [ids[2]]
    assert '5.0%' in rec['text']


async def test_ai_analysis_data_usage_cache_and_staleness(client, env, monkeypatch):
    from app.routers import analytics
    provider = SimpleNamespace(complete=AsyncMock(return_value=LLMResult(text='Проверьте новую подачу: это гипотеза.', tokens=123)))
    monkeypatch.setattr(analytics, 'get_llm', lambda: provider)
    endpoint = '/api/analytics/posts/recommendations'
    assert (await client.post(endpoint, headers=as_user(100), json={'days': 30})).status_code == 422
    ids = [await published(env['a'], external=str(i)) for i in range(3)]
    for pid in ids:
        await save(client, pid, {'views': 100, 'reactions': 10})
    assert (await client.post(endpoint, headers=as_user(101), json={'days': 30})).status_code == 403
    first = await client.post(endpoint, headers=as_user(100), json={'days': 30})
    assert first.status_code == 200, first.text
    assert first.json()['stale'] is False
    second = await client.post(endpoint, headers=as_user(100), json={'days': 30})
    assert second.json() == first.json()
    provider.complete.assert_awaited_once()
    async with SessionLocal() as session:
        assert (await session.execute(select(UsageCost).where(UsageCost.company_id == env['a']))).scalar_one().tokens == 123
    await save(client, ids[0], {'views': 101})
    assert (await dashboard(client))['ai_advice']['stale'] is True
    assert (await dashboard(client, user=200))['ai_advice'] is None


async def test_ai_budget(client, env, monkeypatch):
    from app.routers import analytics
    provider = SimpleNamespace(complete=AsyncMock())
    monkeypatch.setattr(analytics, 'get_llm', lambda: provider)
    for i in range(3):
        await save(client, await published(env['a'], external=str(i)), {'views': 1})
    async with SessionLocal() as session:
        company = await session.get(Company, env['a'])
        company.monthly_token_limit = 1
        session.add(UsageCost(company_id=env['a'], kind='llm', tokens=2))
        await session.commit()
    response = await client.post('/api/analytics/posts/recommendations', headers=as_user(100), json={'days': 30})
    assert response.status_code == 429
    provider.complete.assert_not_awaited()


async def test_publication_records_channel_and_time(env):
    from app.platforms import REGISTRY
    from app.platforms.base import PublishResult
    REGISTRY['telegram'] = SimpleNamespace(publish=AsyncMock(return_value=PublishResult(external_id='42', channel_id='-100456')))
    pid = await published(env['a'], status='approved', dated=False)
    async with SessionLocal() as session:
        post = await services.publish_post(session, pid)
        assert post.status == 'published'
        assert post.published_at is not None
        assert post.published_channel_id == '-100456'
        assert post.external_id == '42'


async def test_reactions_with_same_timestamp_use_update_id(client, env):
    await published(env['a'])
    now = datetime.now(timezone.utc).replace(microsecond=0)
    event = SimpleNamespace(chat=SimpleNamespace(id=-100123), message_id=12, date=now, reactions=[SimpleNamespace(total_count=1)])
    await tg.on_reaction_count(event, event_update=SimpleNamespace(update_id=100))
    event.reactions = [SimpleNamespace(total_count=2)]
    await tg.on_reaction_count(event, event_update=SimpleNamespace(update_id=101))
    event.reactions = [SimpleNamespace(total_count=99)]
    await tg.on_reaction_count(event, event_update=SimpleNamespace(update_id=100))
    assert (await dashboard(client))['posts'][0]['metrics']['reactions']['value'] == 2


async def test_existing_database_migration_preserves_published_posts(tmp_path, monkeypatch):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from app import db

    migration_engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path}/legacy.db')
    try:
        async with migration_engine.begin() as connection:
            await connection.execute(text('CREATE TABLE posts (id INTEGER PRIMARY KEY, company_id INTEGER, platform VARCHAR(20), text TEXT, status VARCHAR(20), created_at DATETIME)'))
            await connection.execute(text("INSERT INTO posts (id,company_id,platform,text,status) VALUES (1,1,'telegram','Existing post','published')"))
        monkeypatch.setattr(db, 'engine', migration_engine)
        await db.init_db()
        await db.init_db()  # повторный старт безопасен
        async with migration_engine.connect() as connection:
            row = (await connection.execute(text('SELECT text,status,published_at,published_channel_id FROM posts'))).one()
            assert tuple(row) == ('Existing post', 'published', None, '')
            assert (await connection.execute(text('SELECT COUNT(*) FROM post_metrics'))).scalar_one() == 0
            assert (await connection.execute(text('SELECT COUNT(*) FROM analytics_advice'))).scalar_one() == 0
    finally:
        await migration_engine.dispose()
