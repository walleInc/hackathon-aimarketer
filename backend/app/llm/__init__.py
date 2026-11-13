from ..config import settings
from .base import LLMProvider


def get_llm() -> LLMProvider:
    """Провайдер выбирается настройкой LLM_PROVIDER — остальной код от него не зависит."""
    if settings.llm_provider == "openai":
        from .openai_api import OpenAIProvider

        return OpenAIProvider()
    if settings.llm_provider == "chatgpt_account":
        from .chatgpt_account import ChatGPTAccountProvider

        return ChatGPTAccountProvider()
    from .stub import StubProvider

    return StubProvider()
