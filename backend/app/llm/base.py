from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResult:
    text: str
    tokens: int = 0  # всего (вход + выход), как вернул провайдер
    cost_usd: float = 0.0  # если провайдер сам отдаёт цену; иначе считается по тарифу из настроек
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMProvider(Protocol):
    async def complete(self, system: str, messages: list[dict], json_mode: bool = False) -> LLMResult:
        """messages: [{"role": "user"|"assistant", "content": str}]"""
        ...

    async def generate_image(self, prompt: str, reference: bytes | None = None) -> str | None:
        """Возвращает путь вида /media/xxx.png или URL; None, если изображение не получено."""
        ...
