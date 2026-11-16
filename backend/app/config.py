from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment variables / .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Melodia API"
    environment: str = "development"  # development | test | production
    debug: bool = False
    log_level: str = "INFO"

    # Database
    database_url: str = "postgresql+psycopg://melodia:melodia@localhost:5432/melodia"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False

    # Cache (empty -> in-process memory cache, fine for a single dev instance only)
    redis_url: str = ""

    # Security
    jwt_secret: str = Field(default="change-me-in-env", min_length=16)
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 15
    refresh_token_ttl_days: int = 30

    # CORS (comma separated)
    cors_origins: str = "*"

    # Music provider (GaanaPy service)
    gaanapy_base_url: str = "http://localhost:8001"
    provider_timeout_seconds: float = 30.0
    provider_retries: int = 2
    catalog_cache_ttl_seconds: int = 900
    search_cache_ttl_seconds: int = 300
    # Stream URLs carry their own expiry; refresh this long before it.
    stream_refresh_margin_seconds: int = 600
    verify_stream_quality: bool = True

    default_languages: str = "English,Hindi"

    # Lyrics (LRCLIB is free and returns time-synced LRC lyrics)
    lyrics_base_url: str = "https://lrclib.net"
    lyrics_user_agent: str = "Melodia/1.0 (self-hosted music app)"
    lyrics_enabled: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def default_language_list(self) -> list[str]:
        return [lang.strip() for lang in self.default_languages.split(",") if lang.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
