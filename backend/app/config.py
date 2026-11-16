from functools import lru_cache
from typing import Literal

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

    # Music provider: "audius" (public Audius API, artist-uploaded music) or "gaana"
    # (the GaanaPy service; Gaana blocks many hosting IPs). Indian film / label and
    # international catalogue (e.g. "Tum Hi Ho", "Taylor Swift") is only on Gaana: set
    # MUSIC_PROVIDER=gaana for it.
    music_provider: Literal["audius", "gaana"] = "audius"
    audius_base_url: str = "https://api.audius.co/v1"
    # Audius asks every client to identify itself with an app name.
    audius_app_name: str = "Melodia"
    gaanapy_base_url: str = "http://localhost:8001"
    provider_timeout_seconds: float = 30.0
    # Retries only cover GaanaPy itself being unreachable (connect errors; never read
    # timeouts). When Gaana refuses a request (GaanaPy answers 503 "blocked"), retrying
    # just prolongs the block, so the client backs off instead: no Gaana calls for the
    # cooldown (at least GaanaPy's retry_after), doubling on each repeat up to the max.
    provider_retries: int = 2
    provider_block_cooldown_seconds: int = 60
    provider_block_cooldown_max_seconds: int = 600
    catalog_cache_ttl_seconds: int = 900
    search_cache_ttl_seconds: int = 300
    # Each search section (songs, albums, ...) gets this long; a slow one is reported in
    # `errors` while the others are returned.
    search_section_timeout_seconds: float = 10.0
    # Home lists (trending, new releases, charts) change slowly; each refresh costs one
    # Gaana request per song, so keep them longer and show fewer songs per row.
    home_cache_ttl_seconds: int = 3600
    home_section_size: int = 12
    home_artist_count: int = 4
    # Home shows a "Trending in <language>" row for the user's languages first, then for
    # these (up to 6 rows), plus "International hits" in `international_language`.
    home_languages: str = "Hindi,Malayalam,Tamil,Telugu,Punjabi"
    international_language: str = "English"
    # Deadline for each Home provider row; a late row falls back to its last good copy
    # (marked stale) or is reported in `errors`.
    home_section_timeout_seconds: float = 12.0
    # Song/artist metadata rarely changes; long-lived so lyrics and artist cards never
    # need a fresh Gaana lookup.
    metadata_cache_ttl_seconds: int = 86400
    # Last good copy of any catalogue response, served while Gaana is blocking us.
    stale_cache_ttl_seconds: int = 86400
    # "Not found" answers are remembered too, so missing items aren't re-requested.
    not_found_cache_ttl_seconds: int = 900
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
    def home_language_list(self) -> list[str]:
        return [lang.strip().title() for lang in self.home_languages.split(",") if lang.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
