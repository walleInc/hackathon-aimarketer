"""Провайдер «через существующий аккаунт ChatGPT» (критерий приёмки №12).

ЗАГОТОВКА. Техническую возможность подключения нужно проверить отдельно
(официальный способ авторизации, доступные функции, ограничения и условия использования)
и зафиксировать результат в docs/features_and_limits.md.

Реализуйте тот же интерфейс, что и LLMProvider (complete / generate_image) —
остальной код менять не придётся. До проверки используйте LLM_PROVIDER=openai.
"""
from .base import LLMResult


class ChatGPTAccountProvider:
    async def complete(self, system: str, messages: list[dict], json_mode: bool = False) -> LLMResult:
        raise NotImplementedError("Подключение через аккаунт ChatGPT ещё не реализовано")

    async def generate_image(self, prompt: str) -> str | None:
        raise NotImplementedError("Подключение через аккаунт ChatGPT ещё не реализовано")
