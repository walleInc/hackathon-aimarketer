"""Публикация во ВКонтакте: wall.post, загрузка картинки и разбор ошибок VK API."""
from urllib.parse import parse_qs

import httpx
import pytest

from app.config import settings
from app.media import media_path
from app.models import SocialAccount
from app.platforms.vk import VkError, VkPlatform
from app.security import encrypt

from .conftest import as_user

IMAGE_URL = "/media/cards/vk-test.png"


def _account(channel: str = "-42") -> SocialAccount:
    return SocialAccount(company_id=1, platform="vk", channel_id=channel, token_encrypted=encrypt("token"))


def _write_image() -> None:
    path = media_path(IMAGE_URL)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xd8\xff\xe0fake-jpeg")


def _platform(handler) -> VkPlatform:
    return VkPlatform(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


async def test_publish_uploads_photo_and_posts_to_community_wall():
    calls: list[tuple[str, dict]] = []

    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append((url, parse_qs(request.content.decode()) if url.startswith("https://api.vk.com/") else {}))
        if url.endswith("photos.getWallUploadServer"):
            return httpx.Response(200, json={"response": {"upload_url": "https://upload.vk.test/photo"}})
        if url == "https://upload.vk.test/photo":
            assert b'name="photo"' in request.content  # файл уходит полем photo
            return httpx.Response(200, json={"server": 11, "photo": '[{"photo":"abc"}]', "hash": "h1"})
        if url.endswith("photos.saveWallPhoto"):
            return httpx.Response(200, json={"response": [{"id": 7, "owner_id": -42, "access_key": "key"}]})
        if url.endswith("wall.post"):
            return httpx.Response(200, json={"response": {"post_id": 99}})
        raise AssertionError(f"неожиданный запрос {url}")

    _write_image()
    result = await _platform(handle).publish(_account(), "Привет, сообщество", IMAGE_URL)

    assert (result.external_id, result.channel_id) == ("99", "-42")
    upload = next(params for url, params in calls if url.endswith("photos.getWallUploadServer"))
    assert upload["group_id"] == ["42"]
    wall = next(params for url, params in calls if url.endswith("wall.post"))
    assert wall["owner_id"] == ["-42"]
    assert wall["from_group"] == ["1"]
    assert wall["message"] == ["Привет, сообщество"]
    assert wall["attachments"] == ["photo-42_7_key"]


async def test_publish_resolves_screen_name_and_works_without_image():
    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("utils.resolveScreenName"):
            assert parse_qs(request.content.decode())["screen_name"] == ["mybrand"]
            return httpx.Response(200, json={"response": {"object_id": 55, "type": "group"}})
        if url.endswith("wall.post"):
            return httpx.Response(200, json={"response": {"post_id": 1}})
        raise AssertionError(f"неожиданный запрос {url}")

    result = await _platform(handle).publish(_account("vk.com/mybrand"), "Текст")

    assert (result.external_id, result.channel_id) == ("1", "-55")


async def test_vk_error_is_shown_to_the_user():
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"error": {"error_code": 214, "error_msg": "Access to adding post denied"}}
        )

    with pytest.raises(VkError, match="Access to adding post denied"):
        await _platform(handle).publish(_account(), "Текст")


async def test_publish_requires_token(monkeypatch):
    monkeypatch.setattr(settings, "vk_access_token", "")
    account = SocialAccount(company_id=1, platform="vk", channel_id="-42")

    with pytest.raises(VkError, match="токен"):
        await _platform(lambda request: httpx.Response(200, json={})).publish(account, "Текст")


async def test_photo_denied_by_community_token_publishes_text_with_warning():
    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("photos.getWallUploadServer"):
            return httpx.Response(200, json={"error": {
                "error_code": 27, "error_msg": "Group authorization failed: method is unavailable with group auth."}})
        if url.endswith("wall.post"):
            params = parse_qs(request.content.decode())
            assert "attachments" not in params  # текст уходит без картинки
            assert params["message"] == ["Текст"]
            return httpx.Response(200, json={"response": {"post_id": 5}})
        raise AssertionError(f"неожиданный запрос {url}")

    _write_image()
    result = await _platform(handle).publish(_account(), "Текст", IMAGE_URL)

    assert (result.external_id, result.channel_id) == ("5", "-42")
    assert "без изображения" in result.warning
    assert "method is unavailable with group auth" in result.warning


async def test_photo_upload_uses_user_token_while_posting_uses_community_token(monkeypatch):
    monkeypatch.setattr(settings, "vk_user_access_token", "user-token")
    tokens: dict[str, str] = {}

    def handle(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        params = parse_qs(request.content.decode()) if url.startswith("https://api.vk.com/") else {}
        if url.endswith("photos.getWallUploadServer"):
            tokens["upload"] = params["access_token"][0]
            return httpx.Response(200, json={"response": {"upload_url": "https://upload.vk.test/photo"}})
        if url == "https://upload.vk.test/photo":
            return httpx.Response(200, json={"server": 1, "photo": '[{"photo":"a"}]', "hash": "h"})
        if url.endswith("photos.saveWallPhoto"):
            return httpx.Response(200, json={"response": [{"id": 3, "owner_id": -42}]})
        if url.endswith("wall.post"):
            tokens["post"] = params["access_token"][0]
            assert params["attachments"] == ["photo-42_3"]
            return httpx.Response(200, json={"response": {"post_id": 8}})
        raise AssertionError(f"неожиданный запрос {url}")

    _write_image()
    result = await _platform(handle).publish(_account(), "Текст", IMAGE_URL)

    assert result.warning == ""
    assert tokens == {"upload": "user-token", "post": "token"}


async def test_admin_connects_vk_community(client, env):
    res = await client.post(
        f"/api/admin/companies/{env['a']}/social",
        headers=as_user(100),
        json={"platform": "vk", "channel_id": "-123456789", "token": "community-token"},
    )
    assert res.status_code == 200
    rows = (await client.get(f"/api/admin/companies/{env['a']}/social", headers=as_user(100))).json()
    assert any(row["platform"] == "vk" and row["channel_id"] == "-123456789" for row in rows)
    assert "community-token" not in str(rows)  # токен наружу не отдаётся


async def test_admin_rejects_unknown_platform(client, env):
    res = await client.post(
        f"/api/admin/companies/{env['a']}/social",
        headers=as_user(100),
        json={"platform": "facebook", "channel_id": "@x"},
    )
    assert res.status_code == 400
