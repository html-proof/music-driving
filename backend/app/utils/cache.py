"""Small in-memory TTL cache with LRU eviction and single-flight loading.

Single-flight matters here: the Flutter app opens Home on many devices at once, and
without it every request would hit Gaana for the same trending list.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable, Union

_MISSING = object()
Ttl = Union[float, Callable[[Any], float]]


class TTLCache:
    def __init__(self, max_entries: int = 5000, clock: Callable[[], float] = time.monotonic):
        self.max_entries = max_entries
        self._clock = clock
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._inflight: dict[str, asyncio.Future] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: str, default: Any = None) -> Any:
        item = self._data.get(key)
        if item is None:
            self.misses += 1
            return default
        expires, value = item
        if expires <= self._clock():
            del self._data[key]
            self.misses += 1
            return default
        self._data.move_to_end(key)
        self.hits += 1
        return value

    def set(self, key: str, value: Any, ttl: float) -> None:
        if ttl <= 0:
            self._data.pop(key, None)
            return
        self._data[key] = (self._clock() + ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self.max_entries:
            self._data.popitem(last=False)

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def clear(self, prefix: str | None = None) -> int:
        if prefix is None:
            n = len(self._data)
            self._data.clear()
            return n
        keys = [k for k in self._data if k.startswith(prefix)]
        for k in keys:
            del self._data[k]
        return len(keys)

    def stats(self) -> dict[str, int]:
        return {"entries": len(self._data), "hits": self.hits, "misses": self.misses}

    async def get_or_load(self, key: str, loader: Callable[[], Awaitable[Any]], ttl: Ttl) -> Any:
        value = self.get(key, _MISSING)
        if value is not _MISSING:
            return value
        pending = self._inflight.get(key)
        if pending is not None:
            return await asyncio.shield(pending)

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        try:
            value = await loader()
        except asyncio.CancelledError:
            future.cancel()
            raise
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()  # mark as retrieved when nobody else was waiting
            raise
        else:
            future.set_result(value)
            self.set(key, value, ttl(value) if callable(ttl) else ttl)
            return value
        finally:
            self._inflight.pop(key, None)
