import asyncio
import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, func

from app import jobs, scheduler, services, task_execution
from app.config import settings
from app.db import SessionLocal, utcnow
from app.models import Task, TaskRun, Post, User
from app.task_schedules import following, local_instant
from tests.conftest import as_user


def body(**kwargs):
    return {"kind": "recommendations", "schedule_kind": "once", "first_run": (utcnow() + timedelta(hours=1)).isoformat() + "Z", **kwargs}


@pytest.mark.parametrize("kind", ["post", "market", "recommendations", "statistics"])
async def test_employee_creates_catalog_task(client, env, kind):
    data = body(kind=kind)
    if kind == "statistics":
        from app.models import SocialAccount
        async with SessionLocal() as s:
            data["channel_id"] = (await s.execute(select(SocialAccount.id).where(SocialAccount.company_id == env["a"]))).scalar_one()
    result = await client.post("/api/tasks", headers=as_user(101), json=data)
    assert result.status_code == 200, result.text
    tasks = (await client.get("/api/tasks", headers=as_user(101))).json()
    assert tasks[0]["kind"] == kind and tasks[0]["next_run"]
    assert {x["id"] for x in (await client.get("/api/tasks/catalog", headers=as_user(101))).json()} == {"post", "market", "recommendations", "statistics"}


@pytest.mark.parametrize("invalid", [
    {"timezone": "no/such_zone"}, {"first_run": "2020-01-01T00:00:00Z"},
    {"first_run": "2030-01-01T00:00:00"}, {"interval_minutes": 0},
    {"schedule_kind": "weekly", "weekdays": []}, {"schedule_kind": "weekly", "weekdays": [7]},
    {"local_time": "25:00"}, {"kind": "statistics"}, {"kind": "unknown"},
])
async def test_invalid_schedule(client, invalid):
    assert (await client.post("/api/tasks", headers=as_user(101), json=body(**invalid))).status_code == 422


async def test_isolation_delete_and_preserve_post(client, env):
    tid = (await client.post("/api/tasks", headers=as_user(101), json=body())).json()["id"]
    for method, path, payload in [("GET", f"/{tid}", None), ("GET", f"/{tid}/runs", None), ("DELETE", f"/{tid}", None), ("PATCH", f"/{tid}", {"active": False})]:
        response = await client.request(method, "/api/tasks" + path, headers=as_user(200), json=payload)
        assert response.status_code == 404
    async with SessionLocal() as s:
        s.add(TaskRun(task_id=tid, company_id=env["a"], scheduled_for=utcnow()))
        post = Post(company_id=env["a"], text="Сохрани меня", status="approved", scheduled_at=utcnow() + timedelta(hours=1))
        s.add(post)
        await s.commit()
        pid = post.id
    assert (await client.delete(f"/api/tasks/{tid}", headers=as_user(101))).status_code == 200
    assert (await client.get("/api/tasks", headers=as_user(101))).json() == []
    assert (await client.get(f"/api/tasks/{tid}/runs", headers=as_user(101))).json()[0]["status"] == "cancelled"
    async with SessionLocal() as s:
        assert (await s.get(Post, pid)).status == "approved"


async def test_timezone_and_dst():
    assert local_instant(datetime(2027, 3, 28).date(), "03:30", "Europe/Riga") == datetime(2027, 3, 28, 1, 0)
    assert local_instant(datetime(2027, 10, 31).date(), "03:30", "Europe/Riga") == datetime(2027, 10, 31, 0, 30)
    task = SimpleNamespace(schedule_kind="weekly", timezone="Europe/Riga", local_time="09:00", weekdays="0,4")
    assert following(task, datetime(2027, 1, 4, 7, 0)) == datetime(2027, 1, 8, 7, 0)


async def test_local_first_run_uses_selected_zone(client):
    r = await client.post("/api/tasks", headers=as_user(101), json={"kind": "post", "schedule_kind": "once", "first_run_local": "2030-01-02T09:00", "timezone": "Europe/Riga"})
    assert r.status_code == 200, r.text
    result = (await client.get(f'/api/tasks/{r.json()["id"]}', headers=as_user(101))).json()
    assert result["next_run"] == "2030-01-02T07:00:00"


async def test_scheduler_restart_and_idempotent_delivery(env, monkeypatch):
    scheduled = utcnow() - timedelta(seconds=1)
    async with SessionLocal() as s:
        task = Task(company_id=env["a"], kind="recommendations", schedule_kind="once", next_run=scheduled)
        s.add(task); await s.commit(); tid = task.id
    dispatch = AsyncMock(side_effect=RuntimeError("queue down"))
    monkeypatch.setattr(jobs, "enqueue", dispatch)
    with pytest.raises(RuntimeError):
        await scheduler.run_due_tasks()
    async with SessionLocal() as s:
        run = (await s.execute(select(TaskRun))).scalar_one()
        assert (await s.get(Task, tid)).next_run is None
        run.queued_at = utcnow() - timedelta(minutes=6)
        await s.commit(); rid = run.id
    dispatch.side_effect = None
    assert await scheduler.run_due_tasks() == 1
    assert await scheduler.run_due_tasks() == 0
    assert dispatch.call_args.args[2] == {"run_id": rid}
    monkeypatch.setattr(task_execution, "build_result", AsyncMock(return_value=("Рекомендации", [], {})))
    await task_execution.execute_run(rid)
    await task_execution.execute_run(rid)
    assert task_execution.build_result.await_count == 1
    async with SessionLocal() as s:
        assert (await s.get(TaskRun, rid)).result == "Рекомендации"


async def test_post_prepared_24h_before_and_late_approval(client, env, monkeypatch):
    target = utcnow() + timedelta(hours=12)
    async with SessionLocal() as s:
        task = Task(company_id=env["a"], kind="post", schedule_kind="once", next_run=target)
        s.add(task); await s.commit()
    monkeypatch.setattr(task_execution, "build_result", AsyncMock(return_value=({"text": "Пост", "image_url": "", "check_notes": ""}, [], {})))
    await scheduler.run_due_tasks()
    async with SessionLocal() as s:
        run = (await s.execute(select(TaskRun))).scalar_one()
        post = await s.get(Post, run.post_id)
        assert post.scheduled_at == target and post.status == "pending_approval"
        post.scheduled_at = utcnow() - timedelta(minutes=1)
        await s.commit(); pid = post.id
    r = await client.post(f"/api/posts/{pid}/decision", headers=as_user(100), json={"decision": "approve", "version": 1})
    assert r.status_code == 200, r.text
    assert r.json()["needs_reschedule"] and r.json()["status"] == "approved"
    assert not env["fake"].published
    await scheduler.run_tick()
    assert not env["fake"].published
    r = await client.post(f"/api/posts/{pid}/reschedule", headers=as_user(100), json={"scheduled_at": (utcnow() + timedelta(hours=1)).isoformat() + "Z", "version": 1})
    assert r.status_code == 200 and not r.json()["needs_reschedule"]
    assert not env["fake"].published
    assert (await client.post(f"/api/posts/{pid}/reschedule", headers=as_user(101), json={"scheduled_at": "2030-01-01T00:00:00Z", "version": 2})).status_code == 403


async def test_delete_during_generation_discards_new_post(client, env, monkeypatch):
    async with SessionLocal() as s:
        task = Task(company_id=env["a"], schedule_kind="once", next_run=utcnow() + timedelta(hours=1))
        s.add(task); await s.commit(); tid = task.id
    async def generate(session, task, run):
        assert (await client.delete(f"/api/tasks/{tid}", headers=as_user(101))).status_code == 200
        return {"text": "Не сохранять", "image_url": "", "check_notes": ""}, [], {}
    monkeypatch.setattr(task_execution, "build_result", generate)
    await scheduler.run_due_tasks()
    async with SessionLocal() as s:
        assert (await s.execute(select(func.count()).select_from(Post))).scalar() == 0
        assert (await s.execute(select(TaskRun.status))).scalar_one() == "cancelled"


async def test_outage_skips_old_posts_and_coalesces_reports(env, monkeypatch):
    now = utcnow()
    async with SessionLocal() as s:
        s.add_all([Task(company_id=env["a"], kind=kind, schedule_kind="interval", interval_minutes=60, next_run=now - timedelta(hours=10)) for kind in ["post", "recommendations"]])
        await s.commit()
    monkeypatch.setattr(jobs, "enqueue", AsyncMock())
    await scheduler.run_due_tasks()
    async with SessionLocal() as s:
        runs = (await s.execute(select(TaskRun).order_by(TaskRun.id))).scalars().all()
        assert len(runs) == 2 and runs[0].status == "skipped" and runs[1].status == "pending"
        assert now - runs[1].scheduled_for < timedelta(minutes=1)


async def test_market_failure_is_visible_and_permanent(env, monkeypatch):
    monkeypatch.setattr(settings, "tavily_api_key", "")
    async with SessionLocal() as s:
        t = Task(company_id=env["a"], kind="market", schedule_kind="once", next_run=utcnow() - timedelta(seconds=1))
        s.add(t); await s.commit()
    await scheduler.run_due_tasks()
    async with SessionLocal() as s:
        run = (await s.execute(select(TaskRun))).scalar_one()
        assert run.status == "failed" and "TAVILY_API_KEY" in run.error


async def test_history_pagination_and_operator_read(client, env):
    tid = (await client.post("/api/tasks", headers=as_user(101), json=body())).json()["id"]
    async with SessionLocal() as s:
        s.add_all([TaskRun(task_id=tid, company_id=env["a"], scheduled_for=utcnow() + timedelta(minutes=i)) for i in range(25)])
        await s.commit()
    first = (await client.get(f"/api/tasks/{tid}/runs", headers=as_user(101))).json()
    second = (await client.get(f'/api/tasks/{tid}/runs?before={first[-1]["id"]}', headers=as_user(101))).json()
    assert len(first) == 20 and len(second) == 5
    r = await client.get("/api/tasks", headers={**as_user(1), "X-Company-Id": str(env["a"])})
    assert r.status_code == 200 and len(r.json()) == 1


async def test_concurrent_ticks_and_workers_create_single_post(env, monkeypatch):
    async with SessionLocal() as s:
        s.add(Task(company_id=env["a"], kind="post", schedule_kind="once", next_run=utcnow() + timedelta(hours=2)))
        await s.commit()
    monkeypatch.setattr(jobs, "enqueue", AsyncMock())
    await asyncio.gather(scheduler.run_due_tasks(), scheduler.run_due_tasks())
    async with SessionLocal() as s:
        runs = (await s.execute(select(TaskRun))).scalars().all()
        assert len(runs) == 1
        rid = runs[0].id
    monkeypatch.setattr(task_execution, "build_result", AsyncMock(return_value=({"text": "Один пост", "image_url": "", "check_notes": ""}, [], {})))
    await asyncio.gather(task_execution.execute_run(rid), task_execution.execute_run(rid))
    assert task_execution.build_result.await_count == 1
    async with SessionLocal() as s:
        assert (await s.execute(select(func.count()).select_from(Post))).scalar() == 1


async def test_expired_worker_lease_is_recovered_and_exhausted_run_fails(env, monkeypatch):
    async with SessionLocal() as s:
        task = Task(company_id=env["a"], kind="recommendations", schedule_kind="once")
        s.add(task); await s.commit()
        s.add_all([TaskRun(task_id=task.id, company_id=env["a"], scheduled_for=utcnow() + timedelta(minutes=i),
                           status="running", attempts=attempts, lease_until=utcnow() - timedelta(minutes=1), queued_at=utcnow() - timedelta(minutes=20)) for i, attempts in enumerate([1, 3])])
        await s.commit()
    monkeypatch.setattr(task_execution, "build_result", AsyncMock(return_value=("Отчёт", [], {})))
    await scheduler.run_due_tasks()
    async with SessionLocal() as s:
        states = (await s.execute(select(TaskRun.status).order_by(TaskRun.id))).scalars().all()
        assert states == ["succeeded", "failed"]


async def test_legacy_task_still_executes_and_keeps_interval(env, monkeypatch):
    async with SessionLocal() as s:
        s.add(Task(company_id=env["a"], prompt="Ежедневный пост", interval_minutes=1440))
        await s.commit()
    monkeypatch.setattr(task_execution, "build_result", AsyncMock(return_value=({"text": "Старый пост", "image_url": "", "check_notes": ""}, [], {})))
    assert await scheduler.run_due_tasks() == 1
    assert await scheduler.run_due_tasks() == 0
    async with SessionLocal() as s:
        post = (await s.execute(select(Post))).scalar_one()
        assert post.scheduled_at is None and post.status == "pending_approval"


async def test_database_upgrade_preserves_legacy_rows_and_adds_unique_index(tmp_path):
    from sqlalchemy import text, inspect
    from sqlalchemy.ext.asyncio import create_async_engine
    from app.db import Base, _add_missing_columns
    migration_engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/old.db")
    async with migration_engine.begin() as conn:
        await conn.execute(text("CREATE TABLE companies (id INTEGER PRIMARY KEY, name VARCHAR(200))"))
        await conn.execute(text("INSERT INTO companies VALUES (1, 'Legacy')"))
        await conn.execute(text("CREATE TABLE tasks (id INTEGER PRIMARY KEY, company_id INTEGER, prompt TEXT, interval_minutes INTEGER, active BOOLEAN, last_run DATETIME)"))
        await conn.execute(text("INSERT INTO tasks VALUES (1, 1, 'Original', 1440, 1, NULL)"))
        await conn.execute(text("CREATE TABLE posts (id INTEGER PRIMARY KEY, company_id INTEGER, text TEXT)"))
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
        await conn.run_sync(_add_missing_columns)  # repeat startup is safe
        row = (await conn.execute(text("SELECT prompt, schedule_kind, kind, active, deleted FROM tasks"))).one()
        assert tuple(row) == ("Original", "legacy", "post", 1, 0)
        indexes = await conn.run_sync(lambda c: inspect(c).get_indexes("posts"))
        assert any(i["name"] == "uq_posts_task_run_id" and i["unique"] for i in indexes)
    await migration_engine.dispose()


async def test_approved_in_advance_publishes_only_at_target(env, monkeypatch):
    from app.handlers import publish
    target = utcnow() + timedelta(hours=1)
    async with SessionLocal() as s:
        task = Task(company_id=env["a"], schedule_kind="once")
        s.add(task); await s.commit()
        run = TaskRun(task_id=task.id, company_id=env["a"], scheduled_for=target)
        s.add(run); await s.commit()
        post = Post(company_id=env["a"], text="По времени", task_run_id=run.id, status="pending_approval", scheduled_at=target)
        s.add(post); await s.commit()
        user = (await s.execute(select(User).where(User.telegram_id == 100))).scalar_one()
        await services.decide(s, post, user, "approve", version=1)
        assert post.status == "approved" and not post.needs_reschedule
        pid = post.id
    assert not env["fake"].published
    monkeypatch.setattr(services, "utcnow", lambda: target + timedelta(seconds=1))
    monkeypatch.setattr("app.handlers.utcnow", lambda: target + timedelta(seconds=1))
    await publish({"post_id": pid}, jobs.JobCtx())
    await publish({"post_id": pid}, jobs.JobCtx())
    assert env["fake"].published == ["По времени"]


async def test_long_outage_does_not_publish_old_approved_post(env):
    async with SessionLocal() as s:
        task = Task(company_id=env["a"], schedule_kind="once")
        s.add(task); await s.commit()
        run = TaskRun(task_id=task.id, company_id=env["a"], scheduled_for=utcnow() - timedelta(hours=2))
        s.add(run); await s.commit()
        post = Post(company_id=env["a"], task_run_id=run.id, text="Просрочен", status="approved", scheduled_at=run.scheduled_for)
        s.add(post); await s.commit(); pid = post.id
    await scheduler.run_tick()
    assert not env["fake"].published
    async with SessionLocal() as s:
        assert (await s.get(Post, pid)).needs_reschedule
