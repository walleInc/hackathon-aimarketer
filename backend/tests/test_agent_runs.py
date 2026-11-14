import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app import agent, cache, memory, runs, scheduler, tg
from app.config import settings
from app.db import SessionLocal, utcnow
from app.llm.base import LLMResult
from app.models import AgentRun, Message, Post, RunDelivery, Task, User

MEMBER = {"X-Dev-User": "101"}
APPROVER = {"X-Dev-User": "100"}


async def user_id(session, telegram_id=101):
    return (await session.execute(select(User.id).where(User.telegram_id == telegram_id))).scalar_one()


async def start(client, text="Напиши пост про услугу", **kwargs):
    response = await client.post('/api/agent/runs', headers=MEMBER, json={"text": text, **kwargs})
    assert response.status_code == 202, response.text
    return (await client.get(f"/api/agent/runs/{response.json()['id']}", headers=MEMBER)).json()


async def test_completion_is_persistent_and_duplicate_job_is_harmless(client, env):
    run = await start(client)
    assert run['status'] == 'completed' and run['post_id']
    assert 'согласование' in run['result'] and 'Тестовая публикация' in run['result']
    assert 'опубликован.' not in run['result']
    async with SessionLocal() as session:
        await runs.execute(session, run['id'])
        assert await session.scalar(select(func.count(Post.id))) == 1
        assert await session.scalar(select(func.count(Message.id))) == 2
        delivery = (await session.execute(select(RunDelivery))).scalar_one()
        assert delivery.telegram_id == 101 and delivery.status == 'pending'
    page = (await client.get('/api/agent/messages', headers=MEMBER)).json()
    assert len(page['items']) == 2 and page['items'][1]['image_url']
    assert (await client.get('/api/agent/runs', headers=MEMBER)).json()[0]['id'] == run['id']


async def test_private_history_and_run_ids_are_isolated(client, env):
    run = await start(client, "Личный секрет сотрудника")
    for headers in [APPROVER, {"X-Dev-User": "200"}]:
        assert (await client.get(f"/api/agent/runs/{run['id']}", headers=headers)).status_code == 404
        assert (await client.get('/api/agent/messages', headers=headers)).json()['items'] == []
        response = await client.post('/api/agent/runs', headers=headers,
                                     json={"text": "Уточнение", "parent_run_id": run['id']})
        assert response.status_code == 404
    assert (await client.get('/api/agent/messages', headers={"X-Dev-User": "1"})).status_code == 403
    assert (await client.post('/api/agent/runs', headers=MEMBER, json={"text": "   "})).status_code == 422


async def test_provider_failure_has_safe_result_and_outbox(client, monkeypatch):
    class Broken:
        async def complete(self, *args, **kwargs):
            raise RuntimeError('secret-api-key should not be exposed')
    monkeypatch.setattr(agent, 'get_llm', lambda: Broken())
    run = await start(client, 'Вопрос о компании')
    assert run['status'] == 'failed' and 'Можно повторить' in run['result']
    assert 'secret-api-key' not in run['error']
    async with SessionLocal() as session:
        assert await session.scalar(select(func.count(RunDelivery.id))) == 1


async def test_budget_failure_is_recorded(client, env, monkeypatch):
    from app.models import Company
    async with SessionLocal() as session:
        company = await session.get(Company, env['a'])
        company.monthly_token_limit = 0
        await session.commit()
    run = await start(client, 'Что сделано?')
    assert run['status'] == 'failed' and run['error']


async def test_history_search_reaches_old_days_without_other_users(client, env, monkeypatch):
    old = utcnow() - timedelta(days=30)
    async with SessionLocal() as session:
        uid, other = await user_id(session), await user_id(session, 100)
        session.add_all([
            Message(company_id=env['a'], user_id=uid, role='user', content='Согласовали кодовое название Лотос', created_at=old),
            Message(company_id=env['a'], user_id=other, role='user', content='Чужой личный секрет Лотос', created_at=old),
            Message(company_id=env['b'], user_id=uid, role='user', content='Чужая компания Лотос', created_at=old),
            Message(company_id=env['a'], role='user', content='Старая переписка без автора Лотос', created_at=old),
            *[Message(company_id=env['a'], user_id=uid, role='user', content=f'Недавнее {i}') for i in range(20)],
        ])
        await session.commit()
    calls = []
    class SearchProvider:
        async def complete(self, system, messages, **kwargs):
            calls.append((system, messages.copy()))
            if len(calls) == 1:
                return LLMResult(text=json.dumps({'action': 'search_history', 'query': 'Лотос'}))
            assert 'Согласовали кодовое название Лотос' in messages[-1]['content']
            assert 'Чужой личный секрет' not in system + messages[-1]['content']
            assert 'Чужая компания' not in system + messages[-1]['content']
            assert 'без автора' not in system + messages[-1]['content']
            return LLMResult(text=json.dumps({'action': 'reply', 'reply': 'Мы согласовали название Лотос.'}))
    monkeypatch.setattr(agent, 'get_llm', lambda: SearchProvider())
    run = await start(client, 'Что мы согласовали в прошлом месяце?')
    assert run['status'] == 'completed' and 'Лотос' in run['result'] and len(calls) == 2


async def test_question_about_post_does_not_force_creation(client, monkeypatch):
    complete = AsyncMock(return_value=LLMResult(text=json.dumps({'action': 'reply', 'reply': 'Короткий формат выбран по вашему заданию.'})))
    monkeypatch.setattr(agent, 'get_llm', lambda: SimpleNamespace(complete=complete))
    run = await start(client, 'Почему вчерашний пост такой короткий?')
    assert run['post_id'] is None and complete.await_count == 1


async def test_parent_result_supplies_material_after_many_messages(client, monkeypatch):
    original = await start(client)
    async with SessionLocal() as session:
        uid = await user_id(session)
        session.add_all([Message(company_id=1, user_id=uid, role='user', content=f'Другое {i}') for i in range(30)])
        await session.commit()
    async def complete(system, messages, **kwargs):
        assert 'Тестовая публикация' in system and 'posts' in system
        return LLMResult(text=json.dumps({'action': 'reply', 'reply': 'Уточняю прошлый результат.'}))
    monkeypatch.setattr(agent, 'get_llm', lambda: SimpleNamespace(complete=complete))
    run = await start(client, 'Почему выбрали этот текст?', parent_run_id=original['id'])
    assert run['status'] == 'completed'


async def test_yesterday_is_exact_utc_range(env, monkeypatch):
    from datetime import datetime
    day = datetime(2026, 11, 14)
    monkeypatch.setattr(memory, 'utcnow', lambda: day + timedelta(seconds=1))
    async with SessionLocal() as session:
        uid = await user_id(session)
        session.add_all([
            Message(company_id=env['a'], user_id=uid, role='user', content='UTC yesterday start', created_at=day - timedelta(days=1)),
            Message(company_id=env['a'], user_id=uid, role='user', content='UTC today', created_at=day),
            Message(company_id=env['a'], user_id=uid, role='user', content='UTC too old', created_at=day - timedelta(days=1, seconds=1)),
        ])
        await session.commit()
        found = await memory.search(session, env['a'], uid, after='2026-11-13', before='2026-11-14')
        assert [r['text'] for r in found if r['source'] == 'messages'] == ['UTC yesterday start']
        context = await memory.context(session, env['a'], uid, 'Что было вчера?')
        assert any(r.get('text') == 'UTC yesterday start' for r in json.loads(context))


async def test_pagination_preserves_older_messages(client):
    for i in range(3):
        await start(client, f'Вопрос {i}')
    page = (await client.get('/api/agent/messages?limit=2', headers=MEMBER)).json()
    older = (await client.get(f"/api/agent/messages?limit=2&before={page['next_cursor']}", headers=MEMBER)).json()
    assert max(m['id'] for m in older['items']) < min(m['id'] for m in page['items'])


async def test_scheduled_runs_notify_creator_or_legacy_approver(client, env):
    async with SessionLocal() as session:
        uid = await user_id(session)
        session.add_all([Task(company_id=env['a'], created_by=uid, prompt='Напиши пост про услугу'),
                         Task(company_id=env['a'], prompt='Напиши пост про продукт')])
        await session.commit()
    assert await scheduler.run_due_tasks() == 2
    assert await scheduler.run_due_tasks() == 0
    async with SessionLocal() as session:
        executions = list((await session.execute(select(AgentRun))).scalars())
        assert len(executions) == 2 and all(r.status == 'completed' and r.task_id for r in executions)
        recipients = list((await session.execute(select(RunDelivery.telegram_id))).scalars())
        assert sorted(recipients) == [100, 101]
        legacy = next(r for r in executions if r.user_id is None)
        legacy_id = legacy.id
    assert (await client.get(f'/api/agent/runs/{legacy_id}', headers=APPROVER)).status_code == 200
    assert (await client.get(f'/api/agent/runs/{legacy_id}', headers=MEMBER)).status_code == 404
    history = (await client.get('/api/agent/messages', headers=APPROVER)).json()['items']
    assert any(m['run_id'] == legacy_id and m['role'] == 'assistant' for m in history)


async def test_delivery_resumes_after_partial_failure_and_does_not_duplicate(client, monkeypatch):
    run = await start(client, 'Вопрос')
    async with SessionLocal() as session:
        record = await session.get(AgentRun, run['id'])
        record.result = '😀' * 4000
        await session.commit()
        did = await session.scalar(select(RunDelivery.id))
    send = AsyncMock(side_effect=[SimpleNamespace(message_id=1), RuntimeError('Telegram unavailable')])
    monkeypatch.setattr(tg, 'bot', SimpleNamespace(send_message=send))
    with pytest.raises(RuntimeError):
        await runs.deliver(did)
    first = send.await_args_list[0].args[1]
    async with SessionLocal() as session:
        delivery = await session.get(RunDelivery, did)
        assert delivery.next_chunk == 1 and delivery.status == 'pending'
    send.reset_mock(side_effect=True)
    send.return_value = SimpleNamespace(message_id=2)
    await runs.deliver(did)
    assert all(call.args[1] != first for call in send.await_args_list)
    count = send.await_count
    await runs.deliver(did)
    assert send.await_count == count
    async with SessionLocal() as session:
        assert (await session.get(RunDelivery, did)).status == 'sent'
    assert all(len(chunk.encode('utf-16-le')) // 2 <= 3500 for chunk in tg.split_text('😀' * 10000))


async def test_recovery_does_not_regenerate_committed_material(env):
    async with SessionLocal() as session:
        uid = await user_id(session)
        post = Post(company_id=env['a'], text='Уже подготовлено', status='pending_approval')
        session.add(post)
        await session.flush()
        run = AgentRun(company_id=env['a'], user_id=uid, prompt='Напиши пост', status='running',
                       started_at=utcnow() - timedelta(hours=1), post_id=post.id)
        session.add(run)
        await session.commit()
        rid = run.id
    await runs.maintain()
    await runs.maintain()
    async with SessionLocal() as session:
        assert (await session.get(AgentRun, rid)).status == 'completed'
        assert await session.scalar(select(func.count(Post.id))) == 1
        assert await session.scalar(select(func.count(Message.id)).where(Message.role == 'assistant')) == 1


async def test_search_by_post_number_and_edit_permissions(client, env):
    async with SessionLocal() as session:
        post = Post(company_id=env['a'], text='Давний материал', created_at=utcnow() - timedelta(days=100))
        session.add(post)
        await session.commit()
        pid = post.id
        found = await memory.search(session, env['a'], await user_id(session), query=f'Почему материал #{pid}?')
        assert any(r['source'] == 'posts' and r['id'] == pid for r in found)
        assert not await memory.search(session, env['b'], await user_id(session, 200), query=f'#{pid}')
    response = await client.post('/api/agent/runs', headers=MEMBER,
                                 json={'kind': 'image', 'text': 'Новая картинка', 'post_id': pid})
    assert response.status_code == 403


async def test_busy_legacy_request_is_final_and_not_executed_later(client, env):
    async with SessionLocal() as session:
        uid = await user_id(session)
    async with cache.lock(f'agent-user:{env["a"]}:{uid}', ttl_sec=60):
        response = await client.post('/api/agent/message', headers=MEMBER, json={'text': 'Напиши пост'})
        assert response.status_code == 200 and 'ещё выполняется' in response.json()['reply']
    await runs.maintain()
    async with SessionLocal() as session:
        assert await session.scalar(select(func.count(Post.id))) == 0
        run = (await session.execute(select(AgentRun))).scalar_one()
        assert run.status == 'failed'


async def test_queued_future_prompt_is_not_used_for_current_answer(env, monkeypatch):
    async def complete(system, messages, **kwargs):
        assert 'Будущий запрос' not in system
        return LLMResult(text=json.dumps({'action': 'reply', 'reply': 'Ответ на первый вопрос'}))
    monkeypatch.setattr(agent, 'get_llm', lambda: SimpleNamespace(complete=complete))
    async with SessionLocal() as session:
        uid = await user_id(session)
        first = await runs.create(session, env['a'], uid, 'Первый вопрос')
        await runs.create(session, env['a'], uid, 'Будущий запрос')
        await runs.execute(session, first.id)
        assert first.status == 'completed'


async def test_queue_handler_result_is_json_serializable(client):
    from app.handlers import agent_run
    from app.jobs import JobCtx
    run = await start(client, 'Вопрос')
    result = await agent_run({'run_id': run['id']}, JobCtx())
    assert json.loads(json.dumps(result))['status'] == 'completed'
