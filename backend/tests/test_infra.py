"""Redis (кэш, лимиты, блокировки, состояние), файлы контекста в S3 и обработчики очередей."""
import pytest

from app import agent, cache, context_files, handlers, services, storage
from app.config import settings
from app.db import SessionLocal, utcnow
from app.jobs import JobCtx
from app.models import Company, Post
from tests.conftest import as_user

ADMIN = as_user(1)


class FakeS3:
    """Хранилище в памяти с теми же ключами, что в Yandex S3: {organization_id}/{файл}."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    async def put(self, org_id, filename, data, content_type="application/octet-stream"):
        key = storage.key_for(org_id, filename)
        self.objects[key] = data
        return key

    async def list_files(self, org_id):
        p = storage.prefix(org_id)
        return [
            storage.StoredFile(k[len(p):], k, len(v), f"etag{len(v)}", utcnow())
            for k, v in self.objects.items() if k.startswith(p)
        ]

    async def get(self, key):
        return self.objects[key]

    async def delete(self, org_id, filename):
        self.objects.pop(storage.key_for(org_id, filename), None)


@pytest.fixture
def s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(storage, "enabled", lambda: True)
    for name in ("put", "list_files", "get", "delete"):
        monkeypatch.setattr(storage, name, getattr(fake, name))
    return fake


# ---------- Redis ----------

async def test_rate_limit_blocks_after_limit(env):
    await cache.rate_limit("t", 2)
    await cache.rate_limit("t", 2)
    with pytest.raises(cache.RateLimited):
        await cache.rate_limit("t", 2)
    await cache.rate_limit("other", 2)  # другой ключ — свой счётчик


async def test_ai_rate_limit_per_company(env, monkeypatch):
    monkeypatch.setattr(settings, "ai_rate_limit_per_min", 2)
    async with SessionLocal() as s:
        replies = [(await agent.handle_message(s, env["a"], None, f"вопрос {i}")).reply for i in range(3)]
        assert replies[2].startswith("Слишком много запросов")
        # лимит изолирован по организациям
        assert not (await agent.handle_message(s, env["b"], None, "вопрос")).reply.startswith("Слишком")


async def test_lock_is_exclusive(env):
    async with cache.lock("x"):
        with pytest.raises(cache.LockBusy):
            async with cache.lock("x"):
                pass
    async with cache.lock("x"):  # после освобождения снова доступна
        pass


async def test_dialog_state_roundtrip(env):
    assert await cache.get_state(7) == ""
    await cache.set_state(7, "revise:12")
    assert await cache.get_state(7) == "revise:12"
    await cache.clear_state(7)
    assert await cache.get_state(7) == ""


async def test_prompt_cached_and_invalidated_on_update(client, env):
    async with SessionLocal() as s:
        first = await agent._system_prompt(s, env["a"])
        company = await s.get(Company, env["a"])
        company.description = "НОВОЕ ОПИСАНИЕ"
        await s.commit()
        assert await agent._system_prompt(s, env["a"]) == first  # из кэша: прямое изменение БД не видно
    r = await client.put(f"/api/admin/companies/{env['a']}", json={"description": "ЧЕРЕЗ API"}, headers=ADMIN)
    assert r.status_code == 200
    async with SessionLocal() as s:
        assert "ЧЕРЕЗ API" in await agent._system_prompt(s, env["a"])  # API сбросил кэш


# ---------- файлы контекста ----------

async def test_context_file_upload_goes_to_org_prefix_and_reaches_prompt(client, env, s3):
    r = await client.post(
        f"/api/admin/companies/{env['a']}/files", headers=ADMIN,
        files={"file": ("прайс.txt", "Цена доставки: 777 рублей".encode(), "text/plain")},
    )
    assert r.status_code == 200, r.text
    assert f"{env['a']}/прайс.txt" in s3.objects  # путь {organization_id}/{файл}
    async with SessionLocal() as s:
        assert "777 рублей" in await agent._system_prompt(s, env["a"])
        assert "777" not in await agent._system_prompt(s, env["b"])  # изоляция организаций
    listing = (await client.get(f"/api/admin/companies/{env['a']}/files", headers=ADMIN)).json()
    assert [f["name"] for f in listing["files"]] == ["прайс.txt"]


async def test_context_file_delete_updates_prompt(client, env, s3):
    await client.post(
        f"/api/admin/companies/{env['a']}/files", headers=ADMIN, files={"file": ("a.md", b"SECRET-FACT", "text/markdown")}
    )
    async with SessionLocal() as s:
        assert "SECRET-FACT" in await agent._system_prompt(s, env["a"])
    assert (await client.delete(f"/api/admin/companies/{env['a']}/files/a.md", headers=ADMIN)).status_code == 200
    async with SessionLocal() as s:
        assert "SECRET-FACT" not in await agent._system_prompt(s, env["a"])


async def test_context_file_rejects_bad_type_and_path_traversal(client, env, s3):
    r = await client.post(
        f"/api/admin/companies/{env['a']}/files", headers=ADMIN, files={"file": ("virus.exe", b"x", "application/x-msdownload")}
    )
    assert r.status_code == 400
    r = await client.post(
        f"/api/admin/companies/{env['a']}/files", headers=ADMIN, files={"file": ("../{}/hack.txt".format(env["b"]), b"x", "text/plain")}
    )
    assert r.status_code == 200
    assert list(s3.objects) == [f"{env['a']}/hack.txt"]  # не вышли за префикс своей организации


async def test_context_files_require_admin(client, env, s3):
    r = await client.get(f"/api/admin/companies/{env['a']}/files", headers=as_user(100))
    assert r.status_code == 403


async def test_storage_failure_does_not_break_agent(env, monkeypatch):
    async def boom(org_id):
        raise RuntimeError("S3 недоступен")

    monkeypatch.setattr(storage, "enabled", lambda: True)
    monkeypatch.setattr(storage, "list_files", boom)
    async with SessionLocal() as s:
        res = await agent.handle_message(s, env["a"], None, "привет")
    assert res.reply


async def test_extract_text_formats():
    assert await context_files.extract_text("a.csv", "x;y".encode()) == "x;y"
    with pytest.raises(context_files.UnsupportedFile):
        await context_files.extract_text("a.zip", b"")


# ---------- очереди ----------

async def _approved_post(env, **kw) -> int:
    async with SessionLocal() as s:
        post = Post(company_id=env["a"], text="t", status="approved", **kw)
        s.add(post)
        await s.commit()
        return post.id


async def test_publish_job_retries_then_notifies_on_last_attempt(env, monkeypatch):
    notified = []

    async def fake_notify(text):
        notified.append(text)

    monkeypatch.setattr(services, "notify_admins", fake_notify)
    post_id = await _approved_post(env)
    calls = {"n": 0}

    async def flaky(account, text, image_url=""):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("VK недоступен")
        return "ext-1"

    env["fake"].publish = flaky
    with pytest.raises(RuntimeError):
        await handlers.publish({"post_id": post_id}, JobCtx(attempt=1, max_attempts=3))
    with pytest.raises(RuntimeError):
        await handlers.publish({"post_id": post_id}, JobCtx(attempt=2, max_attempts=3))
    assert notified == []  # промежуточные сбои не спамят администратора
    result = await handlers.publish({"post_id": post_id}, JobCtx(attempt=3, max_attempts=3))
    assert result == {"status": "published"}
    async with SessionLocal() as s:
        assert (await s.get(Post, post_id)).status == "published"


async def test_publish_job_final_failure_notifies_once(env, monkeypatch):
    notified = []

    async def fake_notify(text):
        notified.append(text)

    monkeypatch.setattr(services, "notify_admins", fake_notify)
    post_id = await _approved_post(env)

    async def always_fail(account, text, image_url=""):
        raise RuntimeError("нет сети")

    env["fake"].publish = always_fail
    await handlers.publish({"post_id": post_id}, JobCtx(attempt=1, max_attempts=1))
    assert len(notified) == 1
    async with SessionLocal() as s:
        assert (await s.get(Post, post_id)).status == "failed"


async def test_publish_job_skips_unapproved_post(env):
    async with SessionLocal() as s:
        post = Post(company_id=env["a"], text="t", status="pending_approval")
        s.add(post)
        await s.commit()
        pid = post.id
    assert await handlers.publish({"post_id": pid}, JobCtx()) == {"skipped": "pending_approval"}
    assert env["fake"].published == []


async def test_analytics_snapshot(env):
    await _approved_post(env)
    await handlers.collect({}, JobCtx())
    async with SessionLocal() as s:
        snap = await handlers.get_snapshot(s, await s.get(Company, env["a"]))
    assert snap["posts_by_status"]["approved"] == 1


async def test_queue_endpoints(client, env):
    r = await client.get("/api/admin/queues", headers=ADMIN)
    assert r.status_code == 200 and r.json()["mode"] == "inline"
    r = await client.get("/api/admin/analytics", headers=ADMIN)
    assert r.status_code == 200 and {x["company_id"] for x in r.json()} == {env["a"], env["b"]}
