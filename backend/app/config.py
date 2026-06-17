from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Medusa"
    environment: str = "development"
    bind_host: str = "0.0.0.0"
    public_port: int = 3737

    database_url: str = Field(
        default="postgresql+psycopg://medusa:medusa@localhost:5432/medusa",
        validation_alias="DATABASE_URL",
    )

    session_cookie_name: str = "medusa_session"
    session_ttl_hours: int = 24 * 14
    admin_email: str = Field(default="admin@medusa.local", validation_alias="MEDUSA_ADMIN_EMAIL")
    admin_password: str = Field(default="medusa", validation_alias="MEDUSA_PASSWORD")
    allow_default_password: bool = Field(default=True, validation_alias="MEDUSA_ALLOW_DEFAULT_PASSWORD")

    data_dir: Path = Field(default=Path("./data"), validation_alias="MEDUSA_DATA_DIR")
    local_storage_dir: Path = Field(default=Path("./data/originals"), validation_alias="MEDUSA_LOCAL_STORAGE_DIR")

    gcs_bucket: str | None = Field(default=None, validation_alias="GCS_BUCKET")
    gcs_prefix: str = Field(default="medusa", validation_alias="GCS_PREFIX")
    google_application_credentials: str | None = Field(
        default=None,
        validation_alias="GOOGLE_APPLICATION_CREDENTIALS",
    )

    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-5.5", validation_alias="OPENAI_MODEL")
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        validation_alias="OPENAI_EMBEDDING_MODEL",
    )

    enable_google_vision: bool = Field(default=True, validation_alias="MEDUSA_ENABLE_GOOGLE_VISION")
    low_text_page_threshold: int = 120
    worker_poll_seconds: float = 2.0

    cors_origins: list[str] = [
        "http://localhost:3737",
        "http://127.0.0.1:3737",
    ]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.local_storage_dir.mkdir(parents=True, exist_ok=True)
    return settings
