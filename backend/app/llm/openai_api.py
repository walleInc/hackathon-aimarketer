import base64
import uuid
from pathlib import Path

import openai
from openai import AsyncOpenAI

from ..config import settings
from .base import LLMResult

MAX_TOKENS = 2000  # ограничивает расход и не даёт провайдеру резервировать максимум контекста


class OpenAIProvider:
    def __init__(self) -> None:
        self.client = AsyncOpenAI(
            api_key=settings.openai_api_key or "not-needed", base_url=settings.openai_base_url or None
        )

    async def complete(self, system: str, messages: list[dict], json_mode: bool = False) -> LLMResult:
        msgs = [{"role": "system", "content": system}, *messages]
        try:
            kwargs = {"response_format": {"type": "json_object"}} if json_mode else {}
            resp = await self.client.chat.completions.create(
                model=settings.openai_model, messages=msgs, max_tokens=MAX_TOKENS, **kwargs
            )
        except openai.BadRequestError:
            if not json_mode:
                raise
            # не все провайдеры поддерживают response_format — повторяем без него (JSON требуется в промпте)
            resp = await self.client.chat.completions.create(
                model=settings.openai_model, messages=msgs, max_tokens=MAX_TOKENS
            )
        u = resp.usage
        return LLMResult(
            text=resp.choices[0].message.content or "",
            tokens=(u.total_tokens or 0) if u else 0,
            prompt_tokens=(u.prompt_tokens or 0) if u else 0,
            completion_tokens=(u.completion_tokens or 0) if u else 0,
        )

    async def generate_image(self, prompt: str) -> str | None:
        try:
            resp = await self.client.images.generate(
                model=settings.openai_image_model, prompt=prompt, size="1024x1024"
            )
        except Exception:
            return None
        item = resp.data[0]
        if getattr(item, "b64_json", None):
            Path(settings.media_dir).mkdir(parents=True, exist_ok=True)
            name = f"{uuid.uuid4().hex}.png"
            (Path(settings.media_dir) / name).write_bytes(base64.b64decode(item.b64_json))
            return f"/media/{name}"
        return getattr(item, "url", None)
