from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite+aiosqlite:///./data.db"

    bot_token: str = ""
    public_url: str = ""
    # webhook | polling. На серверах, куда Telegram не может достучаться (блокировки в РФ), нужен polling:
    # Mini App при этом по-прежнему открывается по PUBLIC_URL.
    bot_mode: str = "webhook"
    webhook_secret: str = "change-me"
    admin_ids: str = ""

    secret_key: str = ""
    dev_auth_bypass: bool = False

    llm_provider: str = "stub"
    openai_api_key: str = ""
    openai_base_url: str = ""  # любой OpenAI-совместимый API: OpenRouter, DeepSeek, Groq, Ollama…
    openai_model: str = "gpt-4o-mini"
    openai_image_model: str = "gpt-image-1"
    # Тариф модели, $ за 1 млн токенов (0 = стоимость не считается). Для Llama 3.3 70B в Cloudflare ≈ 0.29 / 2.25.
    llm_price_input_per_m: float = 0.0
    llm_price_output_per_m: float = 0.0

    ai_images: bool = False  # генерировать картинки моделью (нужен провайдер с поддержкой изображений)
    media_dir: str = "media"
    scheduler_interval_sec: int = 30

    @property
    def admin_id_set(self) -> set[int]:
        return {int(x) for x in self.admin_ids.split(",") if x.strip().isdigit()}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
