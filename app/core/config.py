from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Application
    app_name: str = "pr-review-assistant"
    debug: bool = False
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+asyncpg://app:app@db:5432/review"

    # Redis
    redis_url: str = "redis://redis:6379/0"

    # GitHub
    github_webhook_secret: str = ""
    github_token: str = ""
    github_app_id: str | None = None
    github_app_private_key: str | None = None

    # LLM
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"
    llm_base_url: str = "https://api.openai.com/v1"
    llm_mock: bool = True

    # Review limits
    max_diff_files: int = 30
    max_diff_lines: int = 2000


@lru_cache
def get_settings() -> Settings:
    return Settings()
