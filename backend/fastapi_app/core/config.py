from functools import lru_cache
from pathlib import Path
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "AI Hotel Food Ordering"
    environment: str = "development"
    debug: bool = Field(default=False, validation_alias="APP_DEBUG")

    database_url: str = Field(
        default="postgresql+psycopg://hotel:hotel@localhost:5432/hotel_orders",
        validation_alias="DATABASE_URL",
    )
    auto_create_tables: bool = Field(default=False, validation_alias="AUTO_CREATE_TABLES")

    telegram_bot_token: str = Field(default="", validation_alias="TELEGRAM_BOT_TOKEN")
    telegram_webhook_secret: str = Field(default="", validation_alias="TELEGRAM_WEBHOOK_SECRET")
    telegram_http_timeout_seconds: float = Field(default=30.0, validation_alias="TELEGRAM_HTTP_TIMEOUT_SECONDS")

    ai_provider: str = Field(default="mock", validation_alias="AI_PROVIDER")
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5.5", validation_alias="OPENAI_MODEL")
    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-2.5-flash", validation_alias="GEMINI_MODEL")

    backend_api_key: str = Field(default="change-me-admin-key", validation_alias="BACKEND_API_KEY")
    dashboard_token: str = Field(default="change-me-dashboard-token", validation_alias="DASHBOARD_TOKEN")

    cors_origins: List[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
        validation_alias="CORS_ORIGINS",
    )

    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def telegram_api_base(self) -> str:
        return f"https://api.telegram.org/bot{self.telegram_bot_token}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
