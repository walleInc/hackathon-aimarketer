from .base import Platform
from .telegram import TelegramPlatform

# Новые площадки (vk, max) добавляются сюда — остальной код не меняется.
REGISTRY: dict[str, Platform] = {"telegram": TelegramPlatform()}
