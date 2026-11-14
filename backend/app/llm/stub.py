"""Детерминированный провайдер без внешних вызовов — для разработки и тестов."""
import json

from .base import LLMResult

class StubProvider:
    async def complete(self, system: str, messages: list[dict], json_mode: bool = False) -> LLMResult:
        last = messages[-1]["content"] if messages else ""
        if "ПРОВЕРКА_БРЕНДА" in last:
            return LLMResult(text=json.dumps({"ok": True, "issues": [], "fixed_text": ""}))
        from ..agent import _explicit_creation_request
        if json_mode and _explicit_creation_request(last):
            payload = {
                "action": "create_post",
                "platform": "telegram",
                "post_text": f"Тестовая публикация по запросу: {last}",
                "headline": "Тестовая публикация",
                "card_text": last[:120],
                "image_prompt": last,
                "reply": "Подготовил материал, отправил на согласование.",
            }
        elif json_mode:
            payload = {"action": "reply", "reply": f"Принято: {last}"}
        else:  # переписывание поста по комментарию
            return LLMResult(text=f"{last} (доработано)")
        return LLMResult(text=json.dumps(payload, ensure_ascii=False))

    async def generate_image(self, prompt: str, reference: bytes | None = None) -> str | None:
        return None
