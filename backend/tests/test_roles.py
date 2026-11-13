"""Три роли: оператор (не создаёт материалы), администратор компании (согласует), сотрудник (ставит задачи)."""
import json

from app import agent, tg
from app.llm.base import LLMResult
from tests.conftest import as_user

OPERATOR, COMPANY_ADMIN, EMPLOYEE = as_user(1), as_user(100), as_user(101)


async def test_operator_cannot_create_or_decide(client, env):
    r = await client.post("/api/agent/message", headers={**OPERATOR, "X-Company-Id": str(env["a"])}, json={"text": "Напиши пост"})
    assert r.status_code == 403
    r = await client.post("/api/tasks", headers={**OPERATOR, "X-Company-Id": str(env["a"])}, json={"prompt": "x"})
    assert r.status_code == 403

    post_id = (await client.post("/api/agent/message", headers=COMPANY_ADMIN, json={"text": "Напиши пост"})).json()["post_id"]
    r = await client.post(
        f"/api/posts/{post_id}/decision", headers={**OPERATOR, "X-Company-Id": str(env["a"])}, json={"decision": "approve"}
    )
    assert r.status_code == 403
    assert (await client.get(f"/api/posts/{post_id}", headers={**COMPANY_ADMIN})).json()["status"] == "pending_approval"


async def test_employee_creates_but_cannot_approve_or_edit(client):
    r = await client.post("/api/agent/message", headers=EMPLOYEE, json={"text": "Напиши пост"})
    assert r.status_code == 200 and r.json()["post_id"]
    pid = r.json()["post_id"]
    assert (await client.post(f"/api/posts/{pid}/decision", headers=EMPLOYEE, json={"decision": "approve"})).status_code == 403
    assert (await client.patch(f"/api/posts/{pid}", headers=EMPLOYEE, json={"text": "правка"})).status_code == 403


async def test_author_is_told_about_decision(client, monkeypatch):
    sent: list[tuple[int, str]] = []

    class FakeBot:
        async def send_message(self, chat_id, text, **kw):
            sent.append((chat_id, text))

        async def send_photo(self, *a, **kw):
            pass

    monkeypatch.setattr(tg, "bot", FakeBot())
    pid = (await client.post("/api/agent/message", headers=EMPLOYEE, json={"text": "Напиши пост"})).json()["post_id"]
    assert any(chat == 100 for chat, _ in sent)  # материал ушёл администратору компании
    assert not any(chat == 1 for chat, _ in sent)  # оператору согласование не приходит
    await client.post(f"/api/posts/{pid}/decision", headers=COMPANY_ADMIN, json={"decision": "approve"})
    assert any(chat == 101 and "опубликован" in text for chat, text in sent)


async def test_conversational_answer_to_post_request_is_retried_as_post(client, monkeypatch):
    """Модель ответила беседой на просьбу о посте — агент требует готовый материал."""
    calls: list[str] = []

    class FakeLLM:
        async def complete(self, system, messages, json_mode=False):
            calls.append(messages[-1]["content"])
            if len(calls) == 1:
                return LLMResult(text=json.dumps({"action": "reply", "reply": "Конечно! О чём писать?"}), tokens=10)
            if "create_post" in messages[-1]["content"]:
                return LLMResult(
                    text=json.dumps({"action": "create_post", "post_text": "Готовый пост", "headline": "Заголовок"}), tokens=10
                )
            return LLMResult(text=json.dumps({"ok": True}), tokens=5)

    monkeypatch.setattr(agent, "get_llm", lambda: FakeLLM())
    r = (await client.post("/api/agent/message", headers=EMPLOYEE, json={"text": "Подготовь пост про акцию"})).json()
    assert r["post_id"] is not None


async def test_schedule_task_from_chat(client, monkeypatch):
    class FakeLLM:
        async def complete(self, system, messages, json_mode=False):
            return LLMResult(
                text=json.dumps({"action": "schedule_task", "task_prompt": "Пост про услуги", "interval_minutes": 1440}), tokens=5
            )

    monkeypatch.setattr(agent, "get_llm", lambda: FakeLLM())
    await client.post("/api/agent/message", headers=COMPANY_ADMIN, json={"text": "Готовь материал каждый день"})
    tasks = (await client.get("/api/tasks", headers=COMPANY_ADMIN)).json()
    assert tasks and tasks[0]["interval_minutes"] == 1440


async def test_company_admin_configures_only_own_company(client, env):
    a, b = env["a"], env["b"]
    # свои знания и бренд — можно
    r = await client.post(f"/api/admin/companies/{a}/knowledge", headers=COMPANY_ADMIN, json={"title": "t", "content": "c"})
    assert r.status_code == 200
    doc_id = r.json()["id"]
    assert (await client.put(f"/api/admin/knowledge/{doc_id}", headers=COMPANY_ADMIN, json={"title": "t2", "content": "c2"})).status_code == 200
    assert (await client.put(f"/api/admin/companies/{a}", headers=COMPANY_ADMIN, json={"description": "новое"})).status_code == 200
    # чужая компания — нельзя ни по пути, ни по id сущности
    assert (await client.get(f"/api/admin/companies/{b}/knowledge", headers=COMPANY_ADMIN)).status_code == 403
    assert (await client.post(f"/api/admin/companies/{b}/invite", headers=COMPANY_ADMIN, json={"role": "member"})).status_code == 403
    other = (await client.post(f"/api/admin/companies/{b}/knowledge", headers=as_user(1), json={"title": "x", "content": "y"})).json()["id"]
    assert (await client.delete(f"/api/admin/knowledge/{other}", headers=COMPANY_ADMIN)).status_code == 404
    # видит только свою компанию; создавать компании и менять лимиты расходов нельзя
    ids = [c["id"] for c in (await client.get("/api/admin/companies", headers=COMPANY_ADMIN)).json()]
    assert ids == [a]
    assert [s["id"] for s in (await client.get("/api/admin/stats", headers=COMPANY_ADMIN)).json()] == [a]
    assert (await client.post("/api/admin/companies", headers=COMPANY_ADMIN, json={"name": "Новая"})).status_code == 403
    assert (await client.put(f"/api/admin/companies/{a}", headers=COMPANY_ADMIN, json={"monthly_token_limit": 99999999})).status_code == 403


async def test_employee_has_no_cabinet(client, env):
    assert (await client.get("/api/admin/companies", headers=EMPLOYEE)).status_code == 403
    assert (await client.get(f"/api/admin/companies/{env['a']}/knowledge", headers=EMPLOYEE)).status_code == 403


async def test_company_admin_changes_roles_and_removes_members(client, env):
    from sqlalchemy import select
    from app.db import SessionLocal
    from app.models import User

    async def uid(tg):
        async with SessionLocal() as s:
            return (await s.execute(select(User.id).where(User.telegram_id == tg))).scalar_one()

    a = env["a"]
    emp = await uid(101)
    assert (await client.patch(f"/api/admin/companies/{a}/users/{emp}", headers=COMPANY_ADMIN, json={"role": "approver"})).status_code == 200
    assert (await client.post("/api/agent/message", headers=EMPLOYEE, json={"text": "Напиши пост"})).status_code == 200
    assert (await client.delete(f"/api/admin/companies/{a}/users/{await uid(100)}", headers=COMPANY_ADMIN)).status_code == 409  # себя нельзя
    assert (await client.delete(f"/api/admin/companies/{a}/users/{await uid(200)}", headers=COMPANY_ADMIN)).status_code == 404  # чужая компания
    assert (await client.delete(f"/api/admin/companies/{a}/users/{emp}", headers=COMPANY_ADMIN)).status_code == 200
    assert (await client.post("/api/agent/message", headers=EMPLOYEE, json={"text": "Напиши пост"})).status_code == 400  # доступ отозван
    assert (await client.get("/api/admin/companies", headers=EMPLOYEE)).status_code == 403
