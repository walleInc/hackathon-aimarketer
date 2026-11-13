"""Критерий приёмки №9: данные одной компании недоступны другой."""
from tests.conftest import as_user


async def test_other_company_cannot_see_or_decide_post(client, env):
    r = await client.post("/api/agent/message", json={"text": "Напиши пост"}, headers=as_user(100))
    post_id = r.json()["post_id"]

    assert (await client.get("/api/posts", headers=as_user(200))).json() == []
    assert (await client.get(f"/api/posts/{post_id}", headers=as_user(200))).status_code == 404
    r = await client.post(f"/api/posts/{post_id}/decision", json={"decision": "approve"}, headers=as_user(200))
    assert r.status_code == 404
    assert env["fake"].published == []


async def test_user_cannot_switch_company_with_header(client, env):
    await client.post("/api/agent/message", json={"text": "Напиши пост"}, headers=as_user(100))
    headers = {**as_user(200), "X-Company-Id": str(env["a"])}  # попытка подменить компанию
    assert (await client.get("/api/posts", headers=headers)).json() == []


async def test_admin_endpoints_forbidden_for_clients(client, env):
    assert (await client.get("/api/admin/companies", headers=as_user(100))).status_code == 403
    assert (await client.get("/api/admin/companies", headers=as_user(1))).status_code == 200


async def test_agent_memory_is_per_company(client, env):
    await client.post("/api/agent/message", json={"text": "секретный-факт-А"}, headers=as_user(100))
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import Message

    async with SessionLocal() as s:
        rows = (await s.execute(select(Message).where(Message.company_id == env["b"]))).scalars().all()
    assert rows == []


async def test_unknown_user_rejected_and_tokens_never_exposed(client, env):
    assert (await client.get("/api/me", headers=as_user(999))).status_code == 403
    assert (await client.get("/api/me")).status_code == 401
    r = await client.post(
        f"/api/admin/companies/{env['a']}/social",
        json={"platform": "telegram", "channel_id": "@x", "token": "SECRET-TOKEN"}, headers=as_user(1),
    )
    assert r.status_code == 200
    listing = await client.get(f"/api/admin/companies/{env['a']}/social", headers=as_user(1))
    assert "SECRET-TOKEN" not in listing.text and "token" not in listing.text
