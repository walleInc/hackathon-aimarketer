from dataclasses import dataclass
from typing import Protocol


@dataclass
class LLMResult:
    text: str
    tokens: int = 0
    cost_usd: float = 0.0


class LLMProvider(Protocol):
    async def complete(self, system: str, messages: list[dict], json_mode: bool = False) -> LLMResult:
        """messages: [{"role": "user"|"assistant", "content": str}]"""
        ...

    async def generate_image(self, prompt: str) -> str | None:
        """Возвращает путь вида /media/xxx.png или URL; None, если изображение не получено."""
        ...
