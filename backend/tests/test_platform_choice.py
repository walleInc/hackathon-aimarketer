"""Выбор площадки пользователем: генерация поста из кабинета и задачи по расписанию."""
from .conftest import as_user


async def _connect_vk(client, env) -> None:
    res = await client.post(
        f"/api/admin/companies/{env['a']}/social",
        headers=as_user(100),
        json={"platform": "vk", "channel_id": "-243281798", "token": "community-token"},
    )
    assert res.status_code == 200, res.text


async def test_member_sees_the_platforms_of_the_company(client, env):
    await _connect_vk(client, env)

    res = await client.get("/api/platforms", headers=as_user(101))

    assert res.status_code == 200, res.text
    assert set(res.json()) >= {"telegram", "vk"}


async def test_generate_post_uses_the_chosen_platform(client, env):
    await _connect_vk(client, env)

    res = await client.post(
        "/api/posts/generate", headers=as_user(101), json={"prompt": "Пост про услугу", "platform": "vk"}
    )

    assert res.status_code == 200, res.text
    assert res.json()["platform"] == "vk"


async def test_generate_post_rejects_unconnected_platform(client, env):
    res = await client.post(
        "/api/posts/generate", headers=as_user(101), json={"prompt": "Пост про услугу", "platform": "vk"}
    )

    assert res.status_code == 422
    assert "не подключена" in res.json()["detail"]


async def test_task_keeps_the_chosen_platform(client, env):
    await _connect_vk(client, env)

    created = await client.post(
        "/api/tasks",
        headers=as_user(101),
        json={"kind": "post", "prompt": "Новости компании", "schedule_kind": "legacy", "platform": "vk"},
    )
    assert created.status_code == 200, created.text
    task_id = created.json()["id"]

    tasks = (await client.get("/api/tasks", headers=as_user(101))).json()
    assert next(t for t in tasks if t["id"] == task_id)["platform"] == "vk"


async def test_task_without_platform_stays_automatic(client, env):
    created = await client.post(
        "/api/tasks",
        headers=as_user(101),
        json={"kind": "post", "prompt": "Новости компании", "schedule_kind": "legacy"},
    )

    assert created.status_code == 200, created.text
    tasks = (await client.get("/api/tasks", headers=as_user(101))).json()
    assert next(t for t in tasks if t["id"] == created.json()["id"])["platform"] == ""


async def test_task_rejects_unconnected_platform(client, env):
    res = await client.post(
        "/api/tasks",
        headers=as_user(101),
        json={"kind": "post", "prompt": "Новости компании", "schedule_kind": "legacy", "platform": "vk"},
    )

    assert res.status_code == 422
    assert "не подключена" in res.json()["detail"]
