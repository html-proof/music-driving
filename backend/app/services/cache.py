"""JSON cache with a Redis backend and an in-process fallback for local development."""

import json
import logging
import time
from typing import Any, Protocol

log = logging.getLogger(__name__)


class Cache(Protocol):
    async def get(self, key: str) -> Any | None: ...
    async def set(self, key: str, value: Any, ttl: int) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def ping(self) -> bool: ...
    async def close(self) -> None: ...


class MemoryCache:
    def __init__(self, max_items: int = 5000):
        self._data: dict[str, tuple[float, str]] = {}
        self._max = max_items

    async def get(self, key: str) -> Any | None:
        item = self._data.get(key)
        if not item:
            return None
        expires, raw = item
        if expires < time.monotonic():
            self._data.pop(key, None)
            return None
        return json.loads(raw)

    async def set(self, key: str, value: Any, ttl: int) -> None:
        if ttl <= 0:
            return
        if len(self._data) >= self._max:
            now = time.monotonic()
            for k in [k for k, (exp, _) in self._data.items() if exp < now]:
                self._data.pop(k, None)
            if len(self._data) >= self._max:
                self._data.pop(next(iter(self._data)))
        self._data[key] = (time.monotonic() + ttl, json.dumps(value, default=str))

    async def delete(self, key: str) -> None:
        self._data.pop(key, None)

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        self._data.clear()


class RedisCache:
    def __init__(self, url: str, prefix: str = "melodia:"):
        import redis.asyncio as redis

        self._redis = redis.from_url(url, decode_responses=True)
        self._prefix = prefix

    async def get(self, key: str) -> Any | None:
        try:
            raw = await self._redis.get(self._prefix + key)
        except Exception as exc:  # cache outages must not break requests
            log.warning("Redis GET failed: %s", exc)
            return None
        return json.loads(raw) if raw else None

    async def set(self, key: str, value: Any, ttl: int) -> None:
        if ttl <= 0:
            return
        try:
            await self._redis.set(self._prefix + key, json.dumps(value, default=str), ex=ttl)
        except Exception as exc:
            log.warning("Redis SET failed: %s", exc)

    async def delete(self, key: str) -> None:
        try:
            await self._redis.delete(self._prefix + key)
        except Exception as exc:
            log.warning("Redis DEL failed: %s", exc)

    async def ping(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except Exception:
            return False

    async def close(self) -> None:
        await self._redis.aclose()


def build_cache(redis_url: str, namespace: str = "") -> Cache:
    """`namespace` keeps providers apart in a shared Redis: their catalogue keys
    (`trending:English`, `song:<id>`, last-good copies) would otherwise collide."""
    if redis_url:
        return RedisCache(redis_url, prefix=f"melodia:{namespace}:" if namespace else "melodia:")
    log.warning("REDIS_URL not set: using in-process memory cache (single instance only)")
    return MemoryCache()
