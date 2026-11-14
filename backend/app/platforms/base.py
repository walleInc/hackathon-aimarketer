from dataclasses import dataclass
from typing import Protocol

from ..models import SocialAccount


@dataclass
class PublishResult:
    external_id: str
    channel_id: str
    warning: str = ""  # публикация удалась, но с потерей (например, фото не принято площадкой)


class Platform(Protocol):
    async def publish(self, account: SocialAccount, text: str, image_url: str = "") -> str | PublishResult:
        """Публикует материал и возвращает идентификаторы сообщения и канала."""
        ...
