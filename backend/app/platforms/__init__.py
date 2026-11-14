from .base import Platform
from .telegram import TelegramPlatform
from .vk import VkPlatform

# Новые площадки (max) добавляются сюда — остальной код не меняется.
REGISTRY: dict[str, Platform] = {"telegram": TelegramPlatform(), "vk": VkPlatform()}
