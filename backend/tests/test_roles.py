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
