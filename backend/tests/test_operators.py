"""Управление операторами: добавление/удаление из админки, права и защита от ошибок."""
from sqlalchemy import select

from app.db import SessionLocal
from app.models import User
from tests.conftest import as_user

ADMIN = as_user(1)  # оператор из ADMIN_IDS


async def test_added_operator_gets_admin_access_and_removal_revokes_it(client):
    assert (await client.get("/api/admin/companies", headers=as_user(500))).status_code == 403  # пока никто
    r = await client.post("/api/admin/operators", headers=ADMIN, json={"telegram_id": 500, "name": "Анна"})
    assert r.status_code == 200
    assert (await client.get("/api/admin/companies", headers=as_user(500))).status_code == 200

    ops = {o["telegram_id"]: o for o in (await client.get("/api/admin/operators", headers=ADMIN)).json()}
    assert ops[500]["source"] == "db" and ops[500]["name"] == "Анна"
    assert ops[1]["source"] == "env" and ops[1]["you"] is True

    assert (await client.delete("/api/admin/operators/500", headers=ADMIN)).status_code == 200
    assert (await client.get("/api/admin/companies", headers=as_user(500))).status_code == 403  # доступ отозван сразу


async def test_only_operators_can_manage_operators(client):
    r = await client.post("/api/admin/operators", headers=as_user(100), json={"telegram_id": 600})
    assert r.status_code == 403
    assert (await client.get("/api/admin/operators", headers=as_user(100))).status_code == 403
    assert (await client.delete("/api/admin/operators/1", headers=as_user(100))).status_code == 403


async def test_invalid_telegram_id_rejected(client):
    for bad in (0, -5):
        r = await client.post("/api/admin/operators", headers=ADMIN, json={"telegram_id": bad})
        assert r.status_code == 422


async def test_cannot_remove_self_or_server_level_operator(client):
    await client.post("/api/admin/operators", headers=ADMIN, json={"telegram_id": 500})
    # оператор из ADMIN_IDS не удаляется из кабинета (иначе он вернётся при следующем входе)
    assert (await client.delete("/api/admin/operators/1", headers=as_user(500))).status_code == 409
    assert (await client.delete("/api/admin/operators/500", headers=as_user(500))).status_code == 409  # самого себя
    assert (await client.delete("/api/admin/operators/777", headers=ADMIN)).status_code == 404


async def test_promoting_client_keeps_company_and_demotion_returns_to_member(client, env):
    await client.post("/api/admin/operators", headers=ADMIN, json={"telegram_id": 101})  # сотрудник компании A
    async with SessionLocal() as s:
        u = (await s.execute(select(User).where(User.telegram_id == 101))).scalar_one()
        assert u.role == "admin" and u.company_id == env["a"]

    assert (await client.delete("/api/admin/operators/101", headers=ADMIN)).status_code == 200
    async with SessionLocal() as s:
        u = (await s.execute(select(User).where(User.telegram_id == 101))).scalar_one()
        assert u.role == "member" and u.company_id == env["a"]  # остался в компании, но без прав администратора
    assert (await client.get("/api/admin/companies", headers=as_user(101))).status_code == 403


async def test_operators_added_via_ui_receive_notifications(client, monkeypatch):
    """notify_admins должен знать и операторов из базы, не только из ADMIN_IDS."""
    from app import tg

    sent: list[int] = []

    class FakeBot:
        async def send_message(self, chat_id, text):
            sent.append(chat_id)

    monkeypatch.setattr(tg, "bot", FakeBot())
    await client.post("/api/admin/operators", headers=ADMIN, json={"telegram_id": 500})
    await tg.notify_admins("тест")
    assert {1, 500} <= set(sent)
