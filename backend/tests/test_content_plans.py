import asyncio
import json
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app import agent, content_plans, jobs
from app.config import settings
from app.db import SessionLocal, utcnow
from app.llm.base import LLMResult
from app.models import ContentPlanDay, ContentPlanItem, Post, UsageCost
from tests.conftest import as_user


def plan_body(**kwargs):
    return dict(title="План продвижения", start_date="2030-01-01", end_date="2030-01-02", posts_per_day=2, wishes="Полезные советы", **kwargs)


async def create(client, **kwargs):
    response = await client.post('/api/content-plans', headers=as_user(101), json={**plan_body(), **kwargs})
    assert response.status_code == 202, response.text
    return response.json()['id']


async def detail(client, pid, user=101):
    response = await client.get(f'/api/content-plans/{pid}', headers=as_user(user))
    assert response.status_code == 200, response.text
    return response.json()


async def test_exact_daily_count_and_shared_plan(client):
    pid = await create(client)
    data = await detail(client, pid, 100)
    assert data['status'] == 'ready' and data['completed_days'] == 2
    assert len(data['items']) == 4
    assert [i['planned_date'] for i in data['items']] == ['2030-01-01'] * 2 + ['2030-01-02'] * 2
    assert (await client.get('/api/content-plans', headers=as_user(100))).json()[0]['id'] == pid
    assert all(i['title'] and i['description'] for i in data['items'])


@pytest.mark.parametrize('invalid', [
    {'end_date': '2029-12-31'}, {'end_date': '2030-02-01'}, {'posts_per_day': 0},
    {'posts_per_day': 11}, {'posts_per_day': 1.5}, {'posts_per_day': True}, {'title': '  '},
])
async def test_invalid_plan(client, invalid):
    r = await client.post('/api/content-plans', headers=as_user(101), json={**plan_body(), **invalid})
    assert r.status_code == 422


async def test_company_isolation_and_operator_read_only(client, env):
    pid = await create(client)
    item = (await detail(client, pid))['items'][0]
    for path, method, body in [(f'/{pid}', 'GET', None), (f'/{pid}/retry', 'POST', None),
        (f'/{pid}/items', 'POST', {k: item[k] for k in ('planned_date', 'title', 'description', 'position')}),
        (f'/items/{item["id"]}', 'PATCH', item), (f'/items/{item["id"]}?version=1', 'DELETE', None)]:
        response = await client.request(method, '/api/content-plans' + path, headers=as_user(200), json=body)
        assert response.status_code == 404
    own = await client.get('/api/content-plans', headers={**as_user(101), 'X-Company-Id': str(env['b'])})
    assert own.json()[0]['id'] == pid
    operator = {**as_user(1), 'X-Company-Id': str(env['a'])}
    assert (await client.get(f'/api/content-plans/{pid}', headers=operator)).status_code == 200
    assert (await client.post('/api/content-plans', headers=operator, json=plan_body())).status_code == 403
    assert (await client.delete(f'/api/content-plans/items/{item["id"]}?version=1', headers=operator)).status_code == 403


async def test_edit_move_add_delete_and_stale_versions(client):
    pid = await create(client)
    item = (await detail(client, pid))['items'][0]
    payload = {'title': 'Обновлённая тема', 'description': 'Новая задача', 'planned_date': '2030-01-02', 'position': 3, 'version': 1}
    response = await client.patch(f'/api/content-plans/items/{item["id"]}', headers=as_user(100), json=payload)
    assert response.status_code == 200 and response.json()['version'] == 2
    assert (await client.patch(f'/api/content-plans/items/{item["id"]}', headers=as_user(101), json=payload)).status_code == 409
    assert (await client.delete(f'/api/content-plans/items/{item["id"]}?version=1', headers=as_user(101))).status_code == 409
    assert (await client.patch(f'/api/content-plans/items/{item["id"]}', headers=as_user(101), json={**payload, 'version': 2, 'planned_date': '2030-02-01'})).status_code == 422
    response = await client.post(f'/api/content-plans/{pid}/items', headers=as_user(101), json={k: v for k, v in payload.items() if k != 'version'})
    assert response.status_code == 201
    assert (await client.delete(f'/api/content-plans/items/{item["id"]}?version=2', headers=as_user(101))).status_code == 200
    assert len((await detail(client, pid))['items']) == 4


async def test_template_is_editable_reusable_and_posts_survive_deletion(client, env):
    pid = await create(client)
    item = (await detail(client, pid))['items'][0]
    for prompt in ['Уточнённое задание про товар', 'Другое задание с тем же шаблоном']:
        r = await client.post('/api/posts/generate', headers=as_user(101), json={'prompt': prompt, 'content_plan_item_id': item['id']})
        assert r.status_code == 200, r.text
        assert r.json()['status'] == 'pending_approval' and r.json()['scheduled_at'] is None
    async with SessionLocal() as s:
        posts = (await s.execute(select(Post).where(Post.content_plan_item_id == item['id']))).scalars().all()
        assert len(posts) == 2 and posts[0].content_plan_prompt == 'Уточнённое задание про товар'
        assert 'Уточнённое задание про товар' in posts[0].text
    assert len((await detail(client, pid))['items'][0]['posts']) == 2
    assert (await client.delete(f'/api/content-plans/items/{item["id"]}?version=1', headers=as_user(101))).status_code == 200
    async with SessionLocal() as s:
        assert (await s.execute(select(func.count()).select_from(Post))).scalar() == 2
    assert (await client.post('/api/posts/generate', headers=as_user(101), json={'prompt': 'Пост', 'content_plan_item_id': item['id']})).status_code == 404


async def test_post_without_template_and_bad_access(client, env, monkeypatch):
    pid = await create(client)
    item = (await detail(client, pid))['items'][0]
    mocked = AsyncMock()
    monkeypatch.setattr(agent, 'generate_post_from_assignment', mocked)
    r = await client.post('/api/posts/generate', headers=as_user(200), json={'prompt': 'Пост', 'content_plan_item_id': item['id']})
    assert r.status_code == 404
    mocked.assert_not_awaited()
    assert (await client.post('/api/posts/generate', headers={**as_user(1), 'X-Company-Id': str(env['a'])}, json={'prompt': 'Пост'})).status_code == 403
    assert (await client.post('/api/posts/generate', headers=as_user(101), json={'prompt': '  '})).status_code == 422


async def test_post_without_template_uses_existing_approval_flow(client):
    r = await client.post('/api/posts/generate', headers=as_user(101), json={'prompt': 'Пост о компании'})
    assert r.status_code == 200 and r.json()['status'] == 'pending_approval'
    async with SessionLocal() as s:
        p = await s.get(Post, r.json()['id'])
        assert p.content_plan_item_id is None and p.content_plan_prompt is None


async def test_retry_recovers_only_failed_days_and_preserves_manual_edits(client, monkeypatch):
    dispatch = AsyncMock()
    monkeypatch.setattr(content_plans, 'dispatch_days', dispatch)
    pid = await create(client)
    async with SessionLocal() as s:
        days = (await s.execute(select(ContentPlanDay).order_by(ContentPlanDay.day))).scalars().all()
        first, second = [d.id for d in days]
    await content_plans.generate_day(first)
    item = (await detail(client, pid))['items'][0]
    await client.patch(f'/api/content-plans/items/{item["id"]}', headers=as_user(101), json={**{k: item[k] for k in ['title', 'description', 'planned_date', 'position', 'version']}, 'title': 'Ручная правка'})
    async with SessionLocal() as s:
        day = await s.get(ContentPlanDay, second)
        day.status, day.attempts, day.error = 'failed', 3, 'Bad response'
        await s.commit()
    assert (await detail(client, pid))['status'] == 'failed'
    await client.post(f'/api/content-plans/{pid}/retry', headers=as_user(101))
    await content_plans.generate_day(first)  # redelivery must not touch completed day
    await content_plans.generate_day(second)
    data = await detail(client, pid)
    assert data['status'] == 'ready' and len(data['items']) == 4
    assert data['items'][0]['title'] == 'Ручная правка'


async def test_generation_rejects_wrong_count_and_records_usage(client, monkeypatch):
    provider = SimpleNamespace(complete=AsyncMock(return_value=LLMResult(text='{"items": []}', tokens=7)))
    monkeypatch.setattr(content_plans, 'get_llm', lambda: provider)
    pid = await create(client, end_date='2030-01-01')
    data = await detail(client, pid)
    assert not data['items'] and data['days'][0]['error']
    async with SessionLocal() as s:
        assert (await s.execute(select(UsageCost.tokens))).scalar_one() == 7


async def test_duplicate_workers_and_lost_dispatch(client, monkeypatch):
    monkeypatch.setattr(content_plans, 'dispatch_days', AsyncMock())
    pid = await create(client, end_date='2030-01-01')
    async with SessionLocal() as s:
        day = (await s.execute(select(ContentPlanDay))).scalar_one()
        day.queued_at = utcnow() - timedelta(minutes=6)
        day.status, day.lease_until, day.attempts = 'running', utcnow() - timedelta(minutes=1), 1
        await s.commit(); day_id = day.id
    await asyncio.gather(content_plans.generate_day(day_id), content_plans.generate_day(day_id))
    assert len((await detail(client, pid))['items']) == 2


async def test_budget_failure_visible_in_plan(client, env):
    from app.models import Company
    async with SessionLocal() as s:
        company = await s.get(Company, env['a']); company.monthly_token_limit = 1
        s.add(UsageCost(company_id=env['a'], kind='llm', tokens=2)); await s.commit()
    pid = await create(client, end_date='2030-01-01')
    data = await detail(client, pid)
    assert data['status'] == 'failed' and 'бюджет' in data['days'][0]['error']


async def test_database_outbox_recovers_lost_dispatch(client, monkeypatch):
    real_dispatch = content_plans.dispatch_days
    monkeypatch.setattr(content_plans, 'dispatch_days', AsyncMock())
    pid = await create(client, end_date='2030-01-01')
    queue = AsyncMock(side_effect=RuntimeError('queue unavailable'))
    monkeypatch.setattr(jobs, 'enqueue', queue)
    with pytest.raises(RuntimeError):
        await real_dispatch(pid)
    async with SessionLocal() as s:
        day = (await s.execute(select(ContentPlanDay))).scalar_one()
        assert day.status == 'pending' and day.queued_at is not None
        day.queued_at = utcnow() - timedelta(minutes=6)
        await s.commit()
    queue.side_effect = None
    await real_dispatch(pid)
    assert queue.await_count == 2


async def test_throttle_does_not_exhaust_attempts(client, monkeypatch):
    from app import cache
    monkeypatch.setattr(cache, 'rate_limit', AsyncMock(side_effect=cache.RateLimited('throttle')))
    pid = await create(client, end_date='2030-01-01')
    data = await detail(client, pid)
    assert data['status'] == 'generating' and data['days'][0]['status'] == 'pending'
    async with SessionLocal() as s:
        assert (await s.execute(select(ContentPlanDay.attempts))).scalar_one() == 0
