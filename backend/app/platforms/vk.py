"""Публикация в сообщество ВКонтакте через VK API: wall.post (+ загрузка картинки на стену)."""
from contextlib import asynccontextmanager
from pathlib import Path

import httpx

from .base import PublishResult
from ..config import settings
from ..media import media_path
from ..models import SocialAccount
from ..security import decrypt

API_URL = "https://api.vk.com/method/"
TEXT_LIMIT = 16384  # ограничение wall.post на длину сообщения
TIMEOUT_SEC = 60


class VkError(RuntimeError):
    pass


async def _image_bytes(image_url: str) -> tuple[bytes, str]:
    if image_url.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=TIMEOUT_SEC, follow_redirects=True) as client:
            res = await client.get(image_url)
            res.raise_for_status()
            return res.content, "photo.jpg"
    path = media_path(image_url) if image_url.startswith("/media/") else Path(image_url)
    if not path.is_file():
        raise VkError(f"Изображение не найдено: {image_url}")
    return path.read_bytes(), path.name


class VkPlatform:
    """Публикует от имени сообщества. Токен: SocialAccount.token_encrypted или VK_ACCESS_TOKEN.

    Подходит ключ сообщества (Управление → Работа с API) с правами «Записи на стене» и «Фотографии»
    либо ключ пользователя-администратора сообщества.
    """

    def __init__(self, client: httpx.AsyncClient | None = None, api_version: str | None = None):
        self._client = client  # подменяется в тестах
        self._api_version = api_version

    @property
    def api_version(self) -> str:
        return self._api_version or settings.vk_api_version

    @asynccontextmanager
    async def _http(self):
        if self._client is not None:
            yield self._client
        else:
            async with httpx.AsyncClient(timeout=TIMEOUT_SEC) as client:
                yield client

    async def _api(self, client: httpx.AsyncClient, method: str, token: str, **params):
        res = await client.post(API_URL + method, data={"access_token": token, "v": self.api_version, **params})
        try:
            data = res.json()
        except ValueError:
            raise VkError(f"VK {method}: некорректный ответ (HTTP {res.status_code})")
        error = data.get("error") if isinstance(data, dict) else None
        if error:
            if isinstance(error, dict):
                raise VkError(f"VK {method}: {error.get('error_msg')} (код {error.get('error_code')})")
            raise VkError(f"VK {method}: {error}")
        return data.get("response") if isinstance(data, dict) else None

    async def _group_id(self, client: httpx.AsyncClient, token: str, channel: str) -> int:
        """-123456789, 123456789, club123, public123, vk.com/mybrand или mybrand."""
        name = channel.strip()
        for prefix in ("https://vk.com/", "http://vk.com/", "vk.com/", "@"):
            if name.startswith(prefix):
                name = name.removeprefix(prefix)
        name = name.split("?")[0].strip("/").split("/")[0]
        if not name:
            raise VkError("Не указан ID сообщества ВКонтакте")
        for prefix in ("club", "public"):
            if name.startswith(prefix) and name[len(prefix):].isdigit():
                return int(name[len(prefix):])
        if name.lstrip("-").isdigit():
            group_id = abs(int(name))
            if group_id == 0:
                raise VkError("Не указан ID сообщества ВКонтакте")
            return group_id
        resolved = await self._api(client, "utils.resolveScreenName", token, screen_name=name)
        if not isinstance(resolved, dict) or resolved.get("type") not in {"group", "page"}:
            raise VkError(f"Сообщество «{channel}» не найдено: укажите числовой ID или короткое имя сообщества")
        return int(resolved["object_id"])

    async def _upload_photo(self, client: httpx.AsyncClient, token: str, group_id: int, image_url: str) -> str:
        server = await self._api(client, "photos.getWallUploadServer", token, group_id=group_id)
        upload_url = (server or {}).get("upload_url")
        if not upload_url:
            raise VkError("VK не выдал адрес загрузки изображения: проверьте права ключа («Фотографии»)")
        content, filename = await _image_bytes(image_url)
        res = await client.post(upload_url, files={"photo": (filename, content, "image/jpeg")})
        try:
            uploaded = res.json()
        except ValueError:
            raise VkError(f"VK: некорректный ответ загрузки изображения (HTTP {res.status_code})")
        if not uploaded.get("photo") or str(uploaded["photo"]).strip() in {"", "[]"}:
            raise VkError("VK отклонил изображение: проверьте формат и размер файла")
        saved = await self._api(
            client, "photos.saveWallPhoto", token, group_id=group_id,
            photo=uploaded["photo"], server=uploaded["server"], hash=uploaded["hash"],
        )
        photo = saved[0] if isinstance(saved, list) and saved else None
        if not photo or "id" not in photo or "owner_id" not in photo:
            raise VkError("VK не сохранил изображение на стене")
        attachment = f"photo{photo['owner_id']}_{photo['id']}"
        if photo.get("access_key"):
            attachment += f"_{photo['access_key']}"
        return attachment

    async def publish(self, account: SocialAccount, text: str, image_url: str = "") -> PublishResult:
        token = decrypt(account.token_encrypted) or settings.vk_access_token
        if not token:
            raise VkError("Не задан токен ВКонтакте для публикации")
        message = text.strip()
        if not message:
            raise VkError("Пустой текст публикации")
        if len(message) > TEXT_LIMIT:
            raise VkError(f"Текст длиннее {TEXT_LIMIT} символов — VK не примет такую публикацию")
        async with self._http() as client:
            group_id = await self._group_id(client, token, account.channel_id)
            params: dict[str, object] = {"owner_id": -group_id, "from_group": 1, "message": message}
            warning = ""
            if image_url:
                try:
                    params["attachments"] = await self._upload_photo(
                        client, settings.vk_user_access_token or token, group_id, image_url
                    )
                except VkError as exc:
                    # Ключ сообщества VK не допускает к загрузке фото на стену (ошибка 27/5).
                    # Текст публикуем, чтобы согласованный материал не потерялся, а причина видна в кабинете.
                    warning = f"Опубликовано без изображения: {exc}"
            result = await self._api(client, "wall.post", token, **params)
            post_id = (result or {}).get("post_id")
            if not post_id:
                raise VkError("VK не вернул идентификатор публикации")
            return PublishResult(external_id=str(post_id), channel_id=str(-group_id), warning=warning)
