import json
from contextlib import asynccontextmanager
from datetime import timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select

from app import telegram_analytics, task_execution
from app.config import settings
from app.db import SessionLocal, utcnow
from app.models import SocialAccount, Task, TaskRun, TelegramConnection
from app.routers import telegram_stats
from app.security import decrypt, encrypt
from tests.conftest import as_user


async def test_telegram_auth_encrypted_owner_bound_and_2fa(client, env, monkeypatch):
    from telethon.errors import SessionPasswordNeededError
    monkeypatch.setattr(settings, "telegram_api_id", 123)
    monkeypatch.setattr(settings, "telegram_api_hash", "fake")
    signin = AsyncMock(side_effect=[SessionPasswordNeededError(None), None])
    fake = SimpleNamespace(send_code_request=AsyncMock(return_value=SimpleNamespace(phone_code_hash="hash")),
                           sign_in=signin, session=SimpleNamespace(save=lambda: "sensitive-session"), log_out=AsyncMock())
    @asynccontextmanager
    async def client_factory(saved=""):
        yield fake
    monkeypatch.setattr(telegram_stats, "telegram_client", client_factory)
    assert (await client.post("/api/telegram-analytics/connect", headers=as_user(101), json={"phone": "+37112345678"})).status_code == 403
    r = await client.post("/api/telegram-analytics/connect", headers=as_user(100), json={"phone": "+37112345678"})
    assert r.status_code == 200, r.text
    async with SessionLocal() as s:
        row = await s.get(TelegramConnection, env["a"])
        assert "37112345678" not in row.pending_encrypted
    r = await client.post("/api/telegram-analytics/verify", headers=as_user(200), json={"code": "12345"})
    assert r.status_code == 422
    r = await client.post("/api/telegram-analytics/verify", headers=as_user(100), json={"code": "12345"})
    assert r.json() == {"step": "password"}
    async with SessionLocal() as s:
        row = await s.get(TelegramConnection, env["a"])
        assert "code" not in json.loads(decrypt(row.pending_encrypted))
    r = await client.post("/api/telegram-analytics/verify", headers=as_user(100), json={"password": "secret-password"})
    assert r.json() == {"step": "connected"}
    async with SessionLocal() as s:
        row = await s.get(TelegramConnection, env["a"])
        assert decrypt(row.session_encrypted) == "sensitive-session"
        assert row.pending_encrypted == "" and row.auth_owner is None
    r = await client.get("/api/telegram-analytics", headers=as_user(101))
    assert r.json()["connected"] and "session" not in r.text and "password" not in r.text
    assert (await client.delete("/api/telegram-analytics", headers=as_user(100))).status_code == 200
    assert fake.log_out.await_count == 1


async def test_login_expiry_and_rate_limit(client, env, monkeypatch):
    monkeypatch.setattr(settings, "telegram_api_id", 123)
    monkeypatch.setattr(settings, "telegram_api_hash", "fake")
    async with SessionLocal() as s:
        s.add(TelegramConnection(company_id=env["a"], pending_encrypted=encrypt("{}"), auth_owner=1, updated_at=utcnow() - timedelta(minutes=11)))
        await s.commit()
    for _ in range(5):
        assert (await client.post("/api/telegram-analytics/verify", headers=as_user(100), json={"code": "1"})).status_code == 422
    assert (await client.post("/api/telegram-analytics/verify", headers=as_user(100), json={"code": "1"})).status_code == 429


async def test_missing_telegram_session_has_useful_error(client):
    r = await client.get("/api/telegram-analytics/available-channels", headers=as_user(100))
    assert r.status_code == 422 and "подключить" in r.json()["detail"]


async def test_statistics_real_counters_and_no_full_access(env, monkeypatch):
    now = utcnow().replace(tzinfo=timezone.utc)
    messages = [SimpleNamespace(id=i, date=now, action=None, views=100, forwards=2,
                               reactions=SimpleNamespace(results=[SimpleNamespace(count=3)])) for i in [1, 2]]
    async def message_iterator(*a, **kw):
        for m in messages:
            yield m
    fake = SimpleNamespace(is_user_authorized=AsyncMock(return_value=True), iter_messages=message_iterator)
    async def get_full(*a):
        return SimpleNamespace(full_chat=SimpleNamespace(participants_count=250, can_view_stats=False))
    class FakeClient:
        is_user_authorized = fake.is_user_authorized
        iter_messages = staticmethod(message_iterator)
        __call__ = staticmethod(get_full)
    @asynccontextmanager
    async def client_factory(saved=""):
        yield FakeClient()
    monkeypatch.setattr(telegram_analytics, "telegram_client", client_factory)
    monkeypatch.setattr(telegram_analytics, "resolve_channel", AsyncMock(return_value=SimpleNamespace(broadcast=True)))
    async with SessionLocal() as s:
        account = (await s.execute(select(SocialAccount).where(SocialAccount.company_id == env["a"]))).scalar_one()
        task = Task(company_id=env["a"], kind="statistics", channel_id=account.id)
        s.add_all([task, TelegramConnection(company_id=env["a"], session_encrypted=encrypt("session"))]); await s.commit()
        result = await telegram_analytics.collect_metrics(s, task)
        assert result["views"] == 200 and result["reactions"] == 6 and result["forwards"] == 4
        assert result["engagement_percent"] == 5 and result["subscribers"] == 250
        assert result["subscribers_change"] is None and result["full_statistics"] is None
        assert len(result["messages"]) == 2 and result["full_statistics_unavailable"]


async def test_market_uses_search_evidence_and_preserves_sources(env, monkeypatch):
    search = AsyncMock(return_value=[{"title": "Обзор", "url": "https://example.com/research", "content": "Спрос вырос"}])
    monkeypatch.setattr(task_execution, "search_market", search)
    async with SessionLocal() as s:
        task = Task(company_id=env["a"], kind="market", prompt="Кофейни в Риге")
        s.add(task); await s.commit()
        run = TaskRun(task_id=task.id, company_id=env["a"], scheduled_for=utcnow())
        s.add(run); await s.commit()
        text, sources, metrics = await task_execution.build_result(s, task, run)
        assert "https://example.com/research" in text
        assert sources == [{"title": "Обзор", "url": "https://example.com/research"}]
        assert "Кофейни" in search.call_args.args[0]
