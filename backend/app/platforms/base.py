from typing import Protocol

from ..models import SocialAccount


class Platform(Protocol):
    async def publish(self, account: SocialAccount, text: str, image_url: str = "") -> str:
        """Публикует материал и возвращает внешний идентификатор поста."""
        ...
