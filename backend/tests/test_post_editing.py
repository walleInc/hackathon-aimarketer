import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from PIL import Image

from app import agent, cache, tg
from app.config import settings
from app.db import SessionLocal
from app.media import media_path
from app.models import Post, User
from sqlalchemy import select


def image_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (48, 32), "blue").save(output, "PNG")
    return output.getvalue()


async def create_post(env, status="pending_approval"):
    async with SessionLocal() as session:
        post = Post(company_id=env["a"], text="Исходный текст", image_url="/media/old.png", status=status)
        session.add(post)
        await session.commit()
        return post.id


async def upload(client, pid, user="100", version="1", data=None):
    return await client.post(
        f"/api/posts/{pid}/image", headers={"X-Dev-User": user},
        data={"version": version}, files={"file": ("image.png", image_bytes() if data is None else data, "image/png")},
    )


async def test_manual_text_edit_preserves_image_and_requires_approval(client, env):
    pid = await create_post(env, "approved")
    result = await client.patch(f"/api/posts/{pid}", headers={"X-Dev-User": "100"}, json={
        "text": "Новый текст", "version": 1,
    })
    assert result.status_code == 200
    post = result.json()
    assert (post["text"], post["image_url"], post["version"], post["status"]) == (
        "Новый текст", "/media/old.png", 2, "pending_approval",
    )
    stale = await client.patch(f"/api/posts/{pid}", headers={"X-Dev-User": "100"}, json={"text": "Старый", "version": 1})
    assert stale.status_code == 409


async def test_upload_preserves_text_and_rejects_stale_approval(client, env):
    pid = await create_post(env, "approved")
    response = await upload(client, pid)
    assert response.status_code == 200
    post = response.json()
    assert post["text"] == "Исходный текст"
    assert post["status"] == "pending_approval" and post["version"] == 2
    with Image.open(media_path(post["image_url"])) as saved:
        assert saved.format == "PNG" and saved.size == (48, 32)
    result = await client.post(f"/api/posts/{pid}/decision", headers={"X-Dev-User": "100"}, json={
        "decision": "approve", "version": 1,
    })
    assert result.status_code == 409
    assert env["fake"].published == []
    assert (await client.get(f"/api/posts/{pid}", headers={"X-Dev-User": "100"})).json()["status"] == "pending_approval"


@pytest.mark.parametrize("status", ["published", "publishing", "rejected"])
async def test_final_posts_cannot_change_image(client, env, status):
    pid = await create_post(env, status)
    assert (await upload(client, pid)).status_code == 409


async def test_upload_validates_content_and_company_permissions(client, env):
    pid = await create_post(env)
    assert (await upload(client, pid, data=b"not an image")).status_code == 422
    assert (await upload(client, pid, data=b"x" * (10 * 1024 * 1024 + 1))).status_code == 422
    assert (await upload(client, pid, user="101")).status_code == 403
    assert (await upload(client, pid, user="200")).status_code == 404
    post = (await client.get(f"/api/posts/{pid}", headers={"X-Dev-User": "100"})).json()
    assert post["version"] == 1 and post["image_url"] == "/media/old.png"


async def test_regeneration_preserves_text_and_failure_preserves_old_image(client, env, monkeypatch):
    pid = await create_post(env)
    monkeypatch.setattr(settings, "ai_images", True)
    from app import post_images
    url = post_images.save_upload(image_bytes())

    class Provider:
        async def generate_image(self, prompt):
            assert "Новая композиция" in prompt and "Исходный текст" in prompt
            return url

    monkeypatch.setattr(agent, "get_llm", lambda: Provider())
    response = await client.post(f"/api/posts/{pid}/image/regenerate", headers={"X-Dev-User": "100"}, json={
        "prompt": "Новая композиция", "version": 1,
    })
    assert response.status_code == 200
    post = response.json()
    assert post["text"] == "Исходный текст" and post["version"] == 2
    assert post["image_url"] != "/media/old.png" and post["status"] == "pending_approval"

    class FailedProvider:
        async def generate_image(self, prompt):
            return None

    monkeypatch.setattr(agent, "get_llm", lambda: FailedProvider())
    failure = await client.post(f"/api/posts/{pid}/image/regenerate", headers={"X-Dev-User": "100"}, json={
        "prompt": "Другая картинка", "version": 2,
    })
    assert failure.status_code == 422
    current = (await client.get(f"/api/posts/{pid}", headers={"X-Dev-User": "100"})).json()
    assert current["version"] == 2 and current["image_url"] == post["image_url"]


async def test_regeneration_checks_permissions_and_switch(client, env, monkeypatch):
    pid = await create_post(env)
    monkeypatch.setattr(settings, "ai_images", False)
    for user, status in [("101", 403), ("200", 404), ("100", 422)]:
        response = await client.post(f"/api/posts/{pid}/image/regenerate", headers={"X-Dev-User": user}, json={
            "prompt": "Новое изображение", "version": 1,
        })
        assert response.status_code == status


def test_telegram_actions_include_the_displayed_version():
    keyboard = tg._approval_kb(7, 3)
    actions = {button.callback_data for row in keyboard.inline_keyboard for button in row}
    assert {f"post:7:3:{action}" for action in ("approve", "edit_text", "regenerate", "upload_image")} <= actions


async def test_telegram_manual_text_and_upload_flows(client, env):
    pid = await create_post(env)
    async with SessionLocal() as session:
        user_id = (await session.execute(select(User.id).where(User.telegram_id == 100))).scalar_one()
    await cache.set_state(user_id, f"edit_text:{pid}:1")
    message = SimpleNamespace(from_user=SimpleNamespace(id=100), text="Текст из Telegram", answer=AsyncMock())
    await tg.on_text(message)
    post = (await client.get(f"/api/posts/{pid}", headers={"X-Dev-User": "100"})).json()
    assert post["text"] == "Текст из Telegram" and post["version"] == 2
    assert post["image_url"] == "/media/old.png" and await cache.get_state(user_id) == ""

    async def download(file, destination):
        destination.write(image_bytes())

    await cache.set_state(user_id, f"upload_image:{pid}:2")
    photo = SimpleNamespace(
        from_user=SimpleNamespace(id=100), photo=[], document=SimpleNamespace(file_size=100),
        bot=SimpleNamespace(download=download), answer=AsyncMock(),
    )
    await tg.on_post_image(photo)
    post = (await client.get(f"/api/posts/{pid}", headers={"X-Dev-User": "100"})).json()
    assert post["version"] == 3 and post["text"] == "Текст из Telegram"
    assert post["image_url"].startswith("/media/uploads/")
    assert post["status"] == "pending_approval" and await cache.get_state(user_id) == ""

    callback = SimpleNamespace(data=f"post:{pid}:2:approve", from_user=SimpleNamespace(id=100), answer=AsyncMock())
    await tg.on_decision(callback)
    assert "устарела" in callback.answer.call_args.args[0]
    assert env["fake"].published == []


async def test_flux_generation_uses_minimal_request(env, monkeypatch):
    from app.llm.openai_api import OpenAIProvider
    import base64

    generate = AsyncMock(return_value=SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(image_bytes()).decode())]))
    provider = OpenAIProvider.__new__(OpenAIProvider)
    provider.client = SimpleNamespace(images=SimpleNamespace(generate=generate))
    monkeypatch.setattr(settings, "openai_image_model", "black-forest-labs/flux-3-image-klein")
    url = await provider.generate_image("Стеклянный фасад")
    assert url and media_path(url).is_file()
    generate.assert_awaited_once_with(model="black-forest-labs/flux-3-image-klein", prompt="Стеклянный фасад")
