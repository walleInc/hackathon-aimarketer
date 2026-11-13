"""Сквозная проверка воркфлоу с реальным ИИ (провайдер берётся из backend/.env), без Telegram.

Запуск:  cd backend && .venv\\Scripts\\python -m scripts.e2e
Проверяет: создание компании и знаний → задача → пост на согласовании → доработка →
одобрение → публикация (в заглушку) → уточняющий вопрос с памятью → изоляция компаний.
"""
import asyncio
import os
import sys
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp}/e2e.db"
os.environ["DEV_AUTH_BYPASS"] = "true"
os.environ["ADMIN_IDS"] = "1"
os.environ["BOT_TOKEN"] = ""  # Telegram не нужен
os.environ["MEDIA_DIR"] = f"{_tmp}/media"

import httpx  # noqa: E402

from app import platforms  # noqa: E402
from app.config import settings  # noqa: E402
from app.db import SessionLocal, init_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402

published: list[str] = []


class FakePlatform:
    async def publish(self, account, text, image_url=""):
        published.append(text)
        return "fake-1"


results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, info: str = "") -> None:
    results.append((name, ok, info))
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f"\n      {info}" if info else ""))


async def main() -> int:
    print(f"Провайдер: {settings.llm_provider} | модель: {settings.openai_model} | base_url: {settings.openai_base_url or 'default'}\n")
    await init_db()
    platforms.REGISTRY["telegram"] = FakePlatform()
    admin = {"X-Dev-User": "1"}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=180) as c:
        a = (await c.post("/api/admin/companies", headers=admin, json={
            "name": "Стеклотара Лотос", "description": "Производитель стеклянной тары",
            "brand_style": "Деловой, дружелюбный тон. Без восклицательных знаков."})).json()["id"]
        b = (await c.post("/api/admin/companies", headers=admin, json={"name": "Другая компания"})).json()["id"]
        await c.post(f"/api/admin/companies/{a}/knowledge", headers=admin, json={
            "title": "О компании",
            "content": "Компания основана в 2012 году в Казани. Главный продукт — банка «Лотос» объёмом 0,5 л. "
                       "Аудитория: производители консервации и соусов."})
        await c.post(f"/api/admin/companies/{a}/social", headers=admin, json={"channel_id": "@test"})
        await c.post(f"/api/admin/companies/{b}/social", headers=admin, json={"channel_id": "@other"})
        async with SessionLocal() as s:
            s.add_all([User(telegram_id=100, role="approver", company_id=a), User(telegram_id=200, role="approver", company_id=b)])
            await s.commit()
        client, other = {"X-Dev-User": "100"}, {"X-Dev-User": "200"}

        r = (await c.post("/api/agent/message", headers=client, json={"text": "Подготовь пост про нашу банку Лотос для Telegram"})).json()
        pid = r.get("post_id")
        check("1. Агент создал пост из свободного текста", bool(pid), r.get("reply", ""))
        if not pid:
            return report()
        post = (await c.get(f"/api/posts/{pid}", headers=client)).json()
        check("2. Пост ждёт согласования и не опубликован", post["status"] == "pending_approval" and not published, post["text"][:300])
        check("3. Текст использует факты компании", "Лотос" in post["text"], "")

        r = (await c.post(f"/api/posts/{pid}/decision", headers=client, json={"decision": "revise", "comment": "Сделай короче, до 3 предложений"})).json()
        check("4. Доработка: новая версия, снова на согласовании", r["version"] == 2 and r["status"] == "pending_approval", r["text"][:300])

        r = (await c.post(f"/api/posts/{pid}/decision", headers=client, json={"decision": "approve"})).json()
        check("5. Одобрение → публикация ровно один раз", r["status"] == "published" and len(published) == 1, r["status"])

        r = (await c.post("/api/agent/message", headers=client, json={"text": "В каком году основана наша компания?"})).json()
        check("6. Уточняющий вопрос: ответ из базы знаний", "2012" in r["reply"], r["reply"])
        r = (await c.post("/api/agent/message", headers=client, json={"text": "А в каком городе?"})).json()
        check("7. Память диалога (вопрос без контекста)", "Казан" in r["reply"], r["reply"])

        check("8. Другая компания не видит посты", (await c.get("/api/posts", headers=other)).json() == [], "")
        r = (await c.post("/api/agent/message", headers=other, json={"text": "В каком году основана наша компания?"})).json()
        check("9. Другая компания не получает чужие знания", "2012" not in r["reply"] and "Казан" not in r["reply"], r["reply"])

        usage = (await c.get("/api/admin/usage", headers=admin)).json()
        print(f"\nРасходы (токены): {usage}")
    return report()


def report() -> int:
    failed = [n for n, ok, _ in results if not ok]
    print(f"\nИтог: {len(results) - len(failed)}/{len(results)} пройдено" + (f"; не пройдено: {failed}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
