"""Runtime settings, read from environment variables (see backend/.env.example).

Nothing here is secret: the backend has no accounts, database or API keys.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default).strip()


def _int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    return _env(name, "true" if default else "false").lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str) -> list[str]:
    return [p.strip() for p in _env(name, default).split(",") if p.strip()]


@dataclass(frozen=True)
class Settings:
    app_name: str = "Music Hub API"
    version: str = "2.0.0"
    log_level: str = field(default_factory=lambda: _env("LOG_LEVEL", "info"))
    cors_origins: list[str] = field(default_factory=lambda: _list("CORS_ORIGINS", "*"))

    # Languages Gaana accepts for trending / new releases.
    default_language: str = field(default_factory=lambda: _env("DEFAULT_LANGUAGE", "English"))
    languages: list[str] = field(default_factory=lambda: _list(
        "LANGUAGES",
        "English,Hindi,Punjabi,Tamil,Telugu,Bengali,Marathi,Kannada,Malayalam,Gujarati,Bhojpuri",
    ))

    # Upstream (Gaana via GaanaPy)
    upstream_timeout_seconds: int = field(default_factory=lambda: _int("UPSTREAM_TIMEOUT_SECONDS", 20))
    upstream_concurrency: int = field(default_factory=lambda: _int("UPSTREAM_CONCURRENCY", 8))

    # In-memory cache
    cache_max_entries: int = field(default_factory=lambda: _int("CACHE_MAX_ENTRIES", 5000))
    cache_ttl_catalog: int = field(default_factory=lambda: _int("CACHE_TTL_CATALOG", 1800))
    cache_ttl_search: int = field(default_factory=lambda: _int("CACHE_TTL_SEARCH", 600))
    cache_ttl_feed: int = field(default_factory=lambda: _int("CACHE_TTL_FEED", 1800))
    cache_ttl_empty: int = field(default_factory=lambda: _int("CACHE_TTL_EMPTY", 60))

    # Streams: refresh a URL this many seconds before its provider token expires.
    stream_refresh_margin: int = field(default_factory=lambda: _int("STREAM_REFRESH_MARGIN", 900))
    stream_verify: bool = field(default_factory=lambda: _bool("STREAM_VERIFY", True))

    # Lyrics (LRCLIB, free and keyless)
    lyrics_enabled: bool = field(default_factory=lambda: _bool("LYRICS_ENABLED", True))
    lyrics_base_url: str = field(default_factory=lambda: _env("LYRICS_BASE_URL", "https://lrclib.net"))
    lyrics_user_agent: str = field(default_factory=lambda: _env(
        "LYRICS_USER_AGENT", "MusicHub/2.0 (+https://github.com/ZingyTomato/GaanaPy)"))

    # Per-client request limit (requests per minute; 0 disables).
    rate_limit_per_minute: int = field(default_factory=lambda: _int("RATE_LIMIT_PER_MINUTE", 300))
    # Only trust X-Forwarded-For / X-Real-IP from these peers (nginx on the same host).
    trusted_proxies: list[str] = field(default_factory=lambda: _list("TRUSTED_PROXIES", "127.0.0.1,::1"))


def get_settings() -> Settings:
    return Settings()
