"""Local fix: how GaanaPy talks to Gaana without getting blocked.

* Requests identify honestly (aiohttp's own User-Agent) and only ask for JSON.
* Pacing: at most GAANA_MAX_CONCURRENT (default 4) requests in flight, and at least
  GAANA_MIN_INTERVAL_MS (default 200) between request starts.
* Circuit breaker: after a 401/403/429 no request is sent for GAANA_BLOCK_COOLDOWN_SECONDS
  (default 120), doubling for every repeated block up to 900 s; callers get a BlockedError
  right away instead.
* List/search responses are remembered for GAANA_LIST_CACHE_SECONDS (default 600).
"""

import asyncio
import copy
import json
import math
import os
import time
from collections import OrderedDict

from api.errors import BlockedError

DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
}

BLOCK_STATUSES = (401, 403, 429)
MAX_BLOCK_COOLDOWN_SECONDS = 900.0


def _env_float(name: str, default: str) -> float:
    try:
        return float(os.getenv(name, default))
    except ValueError:
        return float(default)


class CircuitBreaker:
    def __init__(self, cooldown: float | None = None, max_cooldown: float = MAX_BLOCK_COOLDOWN_SECONDS,
                 clock=time.monotonic):
        self.base = _env_float("GAANA_BLOCK_COOLDOWN_SECONDS", "120") if cooldown is None else cooldown
        self.max_cooldown = max(max_cooldown, self.base)
        self._clock = clock
        self._open_until = 0.0
        self._cooldown = 0.0
        self._status = 403

    def remaining(self) -> float:
        return max(0.0, self._open_until - self._clock())

    def check(self) -> None:
        """Raise BlockedError while the breaker is open (no Gaana call is made)."""
        remaining = self.remaining()
        if remaining > 0:
            raise BlockedError(self._status, math.ceil(remaining))

    def trip(self, status: int, retry_after: float | None = None) -> int:
        """Record a block; returns the seconds until Gaana may be asked again."""
        self._status = status
        if self.remaining() > 0:
            # Requests that were already in flight when the first block arrived are
            # the same block, not a repeat: don't double the cooldown for them.
            return math.ceil(self.remaining())
        self._cooldown = self.base if self._cooldown <= 0 else min(self._cooldown * 2, self.max_cooldown)
        cooldown = max(self._cooldown, retry_after or 0)
        self._open_until = self._clock() + cooldown
        return math.ceil(cooldown)

    def success(self) -> None:
        self._cooldown = 0.0


class Pacer:
    """Spaces request starts at least `interval` seconds apart (process-wide)."""

    def __init__(self, interval_ms: float | None = None, clock=time.monotonic):
        ms = _env_float("GAANA_MIN_INTERVAL_MS", "200") if interval_ms is None else interval_ms
        self.interval = max(0.0, ms / 1000.0)
        self._clock = clock
        self._next_start = 0.0

    async def wait(self) -> None:
        if self.interval <= 0:
            return
        now = self._clock()
        start = max(now, self._next_start)
        # Reserve the slot before sleeping, so concurrent callers queue up behind it.
        self._next_start = start + self.interval
        if start > now:
            await asyncio.sleep(start - now)


class ResponseCache:
    """In-process TTL cache for list/search JSON responses (song details have their own)."""

    def __init__(self, ttl: float | None = None, max_items: int = 1000, clock=time.monotonic):
        self.ttl = _env_float("GAANA_LIST_CACHE_SECONDS", "600") if ttl is None else ttl
        self.max_items = max_items
        self._clock = clock
        self._data: OrderedDict[str, tuple[float, dict]] = OrderedDict()

    @property
    def enabled(self) -> bool:
        return self.ttl > 0 and self.max_items > 0

    @staticmethod
    def key(method: str, url: str, kwargs: dict) -> str:
        headers = kwargs.get("headers") or {}
        cookie = next((v for k, v in headers.items() if k.lower() == "cookie"), "")
        params = kwargs.get("params")
        if isinstance(params, dict):
            params = sorted((str(k), str(v)) for k, v in params.items())
        return json.dumps([method.upper(), url, params, cookie, kwargs.get("data"), kwargs.get("json")],
                          ensure_ascii=False, default=str)

    def get(self, key: str):
        item = self._data.get(key)
        if item is None:
            return None
        expires, value = item
        if expires <= self._clock():
            self._data.pop(key, None)
            return None
        self._data.move_to_end(key)
        return copy.deepcopy(value)

    def put(self, key: str, value: dict) -> None:
        if not self.enabled:
            return
        self._data[key] = (self._clock() + self.ttl, copy.deepcopy(value))
        self._data.move_to_end(key)
        while len(self._data) > self.max_items:
            self._data.popitem(last=False)


def parse_retry_after(value) -> float | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None
