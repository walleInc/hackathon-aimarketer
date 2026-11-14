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

    tavily_api_key: str = ""
    telegram_api_id: int = 0
    telegram_api_hash: str = ""

    # --- ВКонтакте: публикация в сообщество (wall.post). Пусто = токен берётся из социального аккаунта компании.
    vk_access_token: str = ""
    # Ключ сообщества публикует посты, но VK не даёт ему загружать фото на стену (ошибка 27):
    # для картинок нужен пользовательский ключ с правом photos (необязателен).
    vk_user_access_token: str = ""
    vk_api_version: str = "5.199"

    ai_images: bool = False  # генерировать картинки моделью (нужен провайдер с поддержкой изображений)
    media_dir: str = "media"
    scheduler_interval_sec: int = 30

    # --- Redis: кэш, лимиты, блокировки, состояние диалога, pub/sub, очереди BullMQ ---
    # Пусто = встроенный in-memory Redis (fakeredis) и выполнение задач в том же процессе: для тестов и локальной разработки.
    redis_url: str = ""
    cache_ttl_sec: int = 300
    dialog_state_ttl_sec: int = 86400
    ai_rate_limit_per_min: int = 10  # запросов к AI в минуту на организацию
    ai_rate_limit_per_user_per_min: int = 6  # ...и на одного пользователя
    run_workers: bool = True  # запускать воркеры очередей в этом процессе
    ai_concurrency: int = 2  # одновременных AI-генераций (контроль расходов на LLM)
    ai_org_concurrency: int = 1  # ...из них на одну организацию

    # --- Yandex Object Storage (S3): файлы контекста организации лежат по пути {organization_id}/{файл} ---
    s3_endpoint: str = "https://storage.yandexcloud.net"
    s3_region: str = "ru-central1"
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    context_files_limit: int = 12000  # символов контекста из файлов в системном промпте
    max_context_file_mb: int = 10

    @property
    def admin_id_set(self) -> set[int]:
        return {int(x) for x in self.admin_ids.split(",") if x.strip().isdigit()}


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
