"""Критерии приёмки: нет публикации без согласования, отклонённое не публикуется, дублей нет."""
from app import services
from app.db import SessionLocal
from app.models import Post
from tests.conftest import as_user


async def _ask_post(client):
    r = await client.post("/api/agent/message", json={"text": "Напиши пост про акцию"}, headers=as_user(100))
    assert r.status_code == 200 and r.json()["post_id"]
    return r.json()["post_id"]


async def test_post_is_pending_and_not_published_before_approval(client, env):
    post_id = await _ask_post(client)
    r = await client.get(f"/api/posts/{post_id}", headers=as_user(100))
    assert r.json()["status"] == "pending_approval"
    async with SessionLocal() as s:
        assert await services.publish_post(s, post_id) is None  # публикация заблокирована
        assert await services.publish_due(s) == 0
    assert env["fake"].published == []


async def test_approve_publishes_exactly_once(client, env):
    post_id = await _ask_post(client)
    r = await client.post(f"/api/posts/{post_id}/decision", json={"decision": "approve"}, headers=as_user(100))
    assert r.status_code == 200 and r.json()["status"] == "published"
    async with SessionLocal() as s:
        assert await services.publish_post(s, post_id) is None  # повторная публикация невозможна
        await services.publish_due(s)
    assert len(env["fake"].published) == 1


async def test_rejected_never_published(client, env):
    post_id = await _ask_post(client)
    r = await client.post(f"/api/posts/{post_id}/decision", json={"decision": "reject"}, headers=as_user(100))
    assert r.json()["status"] == "rejected"
    async with SessionLocal() as s:
        assert await services.publish_post(s, post_id) is None
    assert env["fake"].published == []
    r = await client.post(f"/api/posts/{post_id}/decision", json={"decision": "approve"}, headers=as_user(100))
    assert r.status_code == 409  # решение по отклонённому уже не принять


async def test_member_cannot_approve(client, env):
    post_id = await _ask_post(client)
    r = await client.post(f"/api/posts/{post_id}/decision", json={"decision": "approve"}, headers=as_user(101))
    assert r.status_code == 403
    assert env["fake"].published == []


async def test_revise_creates_new_version_requiring_reapproval(client, env):
    post_id = await _ask_post(client)
    r = await client.post(
        f"/api/posts/{post_id}/decision", json={"decision": "revise", "comment": "короче"}, headers=as_user(100)
    )
    body = r.json()
    assert body["status"] == "pending_approval" and body["version"] == 2
    assert env["fake"].published == []


async def test_edit_after_approval_resets_to_pending(client, env):
    async with SessionLocal() as s:
        post = Post(company_id=env["a"], text="x", status="approved", scheduled_at=None, created_by=None)
        # запланированный в будущем одобренный пост
        from datetime import timedelta
        from app.db import utcnow

        post.scheduled_at = utcnow() + timedelta(days=1)
        s.add(post)
        await s.commit()
        pid = post.id
    r = await client.patch(f"/api/posts/{pid}", json={"text": "новый текст"}, headers=as_user(100))
    assert r.json()["status"] == "pending_approval" and r.json()["version"] == 2


async def test_failed_publish_marks_failed(client, env):
    async with SessionLocal() as s:  # у компании нет подключённой площадки
        from sqlalchemy import delete
        from app.models import SocialAccount

        await s.execute(delete(SocialAccount).where(SocialAccount.company_id == env["a"]))
        await s.commit()
    post_id = await _ask_post(client)
    r = await client.post(f"/api/posts/{post_id}/decision", json={"decision": "approve"}, headers=as_user(100))
    assert r.json()["status"] == "failed"
