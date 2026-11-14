import json
from datetime import timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import func, select

from app import marketing, services, task_execution, telegram_analytics
from app.config import settings
from app.db import SessionLocal, utcnow
from app.llm.base import LLMResult
from app.models import (ContentPlanItem, MarketingDocument, MarketingHypothesis, MetricObservation,
                        Post, SocialAccount, SocialMetricSnapshot, Task, TaskRun, TelegramConnection)
from app.security import encrypt
from tests.conftest import as_user


async def state(client, user=101, **params):
    response = await client.get('/api/marketing/state', headers=as_user(user), params=params)
    assert response.status_code == 200, response.text
    return response.json()


async def start(client, kind, user=101, **values):
    return await client.post('/api/marketing/jobs', headers=as_user(user), json={'kind': kind, **values})


async def test_employee_workspace_and_company_isolation(client, env):
    data = await state(client, days=30)
    assert data['permissions'] == {'write': True, 'manage': False}
    assert data['analytics']['totals']['views']['value'] is None
    assert data['analytics']['conversions']['sales'] is None
    response = await client.post('/api/marketing/competitors', headers=as_user(101), json={'name': 'Конкурент', 'website': 'https://example.org'})
    assert response.status_code == 200
    cid = response.json()['id']
    assert (await state(client, 200))['competitors'] == []
    assert (await client.delete(f'/api/marketing/competitors/{cid}', headers=as_user(200))).status_code == 404
    assert (await client.put('/api/marketing/profile', headers=as_user(101), json={'niche': 'X', 'geography': 'Y', 'goals': 'Z'})).status_code == 403
    assert (await client.put('/api/marketing/profile', headers=as_user(100), json={'niche': 'Стекло', 'geography': 'Уфа', 'goals': 'Узнаваемость'})).status_code == 200
    assert (await state(client))['profile']['niche'] == 'Стекло'
    assert (await state(client, 200))['profile']['niche'] == ''
    assert (await client.post('/api/marketing/competitors', headers=as_user(101), json={'name': 'X', 'website': 'javascript:alert(1)'})).status_code == 422
    assert (await start(client, 'report', user=1)).status_code == 400  # operator must choose company


async def test_hypotheses_strategy_plan_and_approval_gate(client, env):
    for kind in ('hypotheses', 'strategy', 'plan'):
        response = await start(client, kind)
        assert response.status_code == 202, response.text
    data = await state(client)
    assert all(r['status'] == 'succeeded' for r in data['runs'])
    assert len(data['hypotheses']) == 1 and len(data['plan']) == 7
    h = data['hypotheses'][0]
    assert (await client.patch(f"/api/marketing/hypotheses/{h['id']}", headers=as_user(101), json={'status': 'confirmed', 'result': ''})).status_code == 422
    assert (await client.patch(f"/api/marketing/hypotheses/{h['id']}", headers=as_user(101), json={'status': 'insufficient', 'result': 'Мало просмотров'})).status_code == 200
    strategy = next(d for d in data['documents'] if d['kind'] == 'strategy')
    assert (await client.post(f"/api/marketing/documents/{strategy['id']}/approve", headers=as_user(101))).status_code == 403
    assert (await client.post(f"/api/marketing/documents/{strategy['id']}/approve", headers=as_user(200))).status_code == 404
    assert (await client.post(f"/api/marketing/documents/{strategy['id']}/approve", headers=as_user(100))).status_code == 200
    from app import agent
    async with SessionLocal() as session:
        assert 'Утверждённая маркетинговая стратегия' in await agent._system_prompt(session, env['a'])
        assert 'Утверждённая маркетинговая стратегия' not in await agent._system_prompt(session, env['b'])
    item = data['plan'][0]
    response = await client.post(f"/api/marketing/plan/{item['id']}/prepare", headers=as_user(101))
    assert response.status_code == 202, response.text
    assert (await client.post(f"/api/marketing/plan/{item['id']}/prepare", headers=as_user(101))).status_code == 409
    async with SessionLocal() as session:
        run = await session.get(TaskRun, response.json()['run_id'])
        post = await session.get(Post, run.post_id)
        assert run.status == 'succeeded'
        assert post.status == 'pending_approval'
        assert post.scheduled_at is None  # manual generation is not an expired scheduled post
        assert env['fake'].published == []
        assert await services.publish_post(session, post.id) is None
    # Work survives a new HTTP read, uses DB state and doesn't regenerate it.
    assert len((await state(client))['plan']) == 7
    assert (await client.get('/api/tasks', headers=as_user(101))).json() == []


async def test_hypothesis_post_is_scoped_and_single(client):
    await start(client, 'hypotheses')
    h = (await state(client))['hypotheses'][0]
    url = f"/api/marketing/hypotheses/{h['id']}/prepare"
    assert (await client.post(url, headers=as_user(200))).status_code == 404
    assert (await client.post(url, headers=as_user(101))).status_code == 202
    assert (await client.post(url, headers=as_user(101))).status_code == 409


async def test_research_sources_candidates_and_invalid_model(client, monkeypatch):
    monkeypatch.setattr(settings, 'tavily_api_key', 'test')
    search = AsyncMock(return_value=[{'title': 'Рынок', 'url': 'https://example.org', 'content': 'Открытые сведения'}])
    monkeypatch.setattr(task_execution, 'search_market', search)
    response = await start(client, 'research')
    assert response.status_code == 202
    data = await state(client)
    doc = data['documents'][0]
    assert doc['sources'] == [{'title': 'Рынок', 'url': 'https://example.org'}]
    assert doc['data']['findings'][0]['source_urls'] == ['https://example.org']
    # A fabricated URL must never become a saved report.
    bad = {'summary': 'X', 'findings': [{'title': 'X', 'detail': 'Y', 'source_urls': ['https://fabricated.invalid']}]}
    monkeypatch.setattr(marketing, 'get_llm', lambda: SimpleNamespace(complete=AsyncMock(return_value=LLMResult(text=json.dumps(bad)))))
    response = await start(client, 'research')
    assert response.status_code == 202
    data = await state(client)
    assert len(data['documents']) == 1
    assert data['runs'][0]['status'] == 'pending'  # durable retry, no fabricated result saved
    assert 'источник' in data['runs'][0]['error']


async def test_missing_sources_and_report_schedule_permissions(client):
    assert (await start(client, 'research')).status_code == 422
    body = {'active': True, 'timezone': 'Asia/Yekaterinburg', 'local_time': '09:00'}
    assert (await client.put('/api/marketing/report-schedule', headers=as_user(101), json=body)).status_code == 403
    assert (await client.put('/api/marketing/report-schedule', headers=as_user(100), json={**body, 'timezone': 'bad'})).status_code == 422
    for _ in range(2):
        assert (await client.put('/api/marketing/report-schedule', headers=as_user(100), json=body)).status_code == 200
    data = await state(client)
    assert data['schedule']['active']
    tid = data['schedule']['id']
    assert (await client.patch(f'/api/tasks/{tid}', headers=as_user(101), json={'active': False})).status_code == 403
    async with SessionLocal() as session:
        assert await session.scalar(select(func.count()).select_from(Task).where(Task.kind == 'report')) == 1
        task = await session.get(Task, tid)
        assert task.weekdays == '0'
        local = task.next_run.replace(tzinfo=timezone.utc).astimezone(__import__('zoneinfo').ZoneInfo(task.timezone))
        assert local.weekday() == 0 and local.hour == 9
    assert (await start(client, 'report')).status_code == 202
    assert any(d['kind'] == 'report' for d in (await state(client))['documents'])


async def test_sync_unifies_app_external_posts_and_keeps_history(client, env, monkeypatch):
    now = utcnow()
    async with SessionLocal() as session:
        account = await session.scalar(select(SocialAccount).where(SocialAccount.company_id == env['a']))
        aid = account.id
        session.add(TelegramConnection(company_id=env['a'], session_encrypted=encrypt('session')))
        post = Post(company_id=env['a'], text='Пост приложения', status='published', external_id='1', published_channel_id='-100123', published_at=now - timedelta(days=1))
        session.add(post)
        await session.commit()
        pid = post.id
    def metrics(at, views):
        return {'channel': '@a', 'resolved_channel': '-100123', 'collected_at': at.isoformat() + 'Z', 'subscribers': 100, 'period_days': 7,
                'messages': [{'id': i, 'date': (now - timedelta(days=1)).isoformat() + '+00:00', 'text': f'Пост {i}', 'format': 'photo', 'views': views, 'reactions': 0, 'forwards': None} for i in (1, 2)]}
    collect = AsyncMock(return_value=metrics(now, 100))
    monkeypatch.setattr(telegram_analytics, 'collect_metrics', collect)
    assert (await start(client, 'sync', channel_id=aid)).status_code == 202
    data = (await state(client))['analytics']
    assert data['sample_size'] == 2  # matching app post is not counted twice
    assert data['totals']['views'] == {'value': 200, 'measured': 2}
    assert data['totals']['reactions']['value'] == 0
    assert data['totals']['forwards']['value'] is None
    assert (await state(client, channel='-100123'))['analytics']['sample_size'] == 2
    assert (await state(client, channel='@a'))['analytics']['sample_size'] == 2
    assert (await state(client))['analytics']['channel_snapshots'][0]['subscribers'] == 100
    assert (await state(client, 200))['analytics']['sample_size'] == 0
    collect.return_value = metrics(now + timedelta(seconds=10), 120)
    assert (await start(client, 'sync', channel_id=aid)).status_code == 202
    async with SessionLocal() as session:
        assert await session.scalar(select(func.count()).select_from(SocialMetricSnapshot)) == 4
        assert await session.scalar(select(func.count()).select_from(MetricObservation).where(MetricObservation.post_id == pid)) == 2
    assert (await state(client))['analytics']['totals']['views']['value'] == 240
    # API registration and old stats share the updated counters.
    response = await client.get('/api/analytics/posts', headers=as_user(100))
    assert response.status_code == 200
    assert response.json()['summary']['views']['total'] == 120


async def test_bad_structured_response_and_budget_do_not_save_documents(client, env, monkeypatch):
    from app.models import Company, UsageCost
    monkeypatch.setattr(marketing, 'get_llm', lambda: SimpleNamespace(complete=AsyncMock(return_value=LLMResult(text='not json'))))
    await start(client, 'hypotheses')
    assert (await state(client))['documents'] == []
    async with SessionLocal() as session:
        c = await session.get(Company, env['a'])
        c.monthly_token_limit = 1
        session.add(UsageCost(company_id=c.id, kind='llm', tokens=2))
        await session.commit()
    await start(client, 'strategy')
    data = await state(client)
    assert data['runs'][0]['status'] == 'failed'
    assert data['documents'] == []


async def test_weekly_report_runs_autonomously_and_notifies_own_managers(client, env, monkeypatch):
    from app import scheduler, tg
    sender = AsyncMock()
    monkeypatch.setattr(tg, 'bot', SimpleNamespace(send_message=sender))
    response = await client.put('/api/marketing/report-schedule', headers=as_user(100),
        json={'active': True, 'timezone': 'Asia/Yekaterinburg', 'local_time': '09:00'})
    assert response.status_code == 200
    async with SessionLocal() as session:
        task = await session.scalar(select(Task).where(Task.company_id == env['a'], Task.kind == 'report'))
        task.next_run = utcnow() - timedelta(seconds=1)
        await session.commit()
    assert await scheduler.run_due_tasks() == 1
    sender.assert_awaited_once()
    assert sender.call_args.args[0] == 100
    assert 'Отчёт' in sender.call_args.args[1]
    assert (await state(client))['documents'][0]['kind'] == 'report'
    assert await scheduler.run_due_tasks() == 0
    sender.assert_awaited_once()
