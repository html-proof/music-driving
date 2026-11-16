import asyncio
import json
import os
import aiohttp
from api.songs.songs import Songs
from api.albums.albums import Albums
from api.artists.artists import Artists
from api.trending.trending import Trending
from api.newreleases.newreleases import NewReleases
from api.charts.charts import Charts
from api.playlists.playlists import Playlists
from api import endpoints
from api.functions import Functions
from api.errors import Errors, UpstreamError, BlockedError, UpstreamUnavailable
from api.discovery.discovery import Discovery
from api.songcache import SongCache
from api.upstream import (
    BLOCK_STATUSES, DEFAULT_HEADERS, CircuitBreaker, Pacer, ResponseCache, parse_retry_after,
)

__all__ = ["GaanaPy", "UpstreamError", "BlockedError", "UpstreamUnavailable"]


class GaanaPy(Songs, Albums, Artists, Trending, NewReleases, Charts, Playlists, Discovery):
    def __init__(self):
        self.aiohttp = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )
        self.api_endpoints = endpoints
        self.functions = Functions()
        self.errors = Errors()
        # Bursts are what get clients rate-limited and blocked, so cap how many requests
        # are in flight together and space their starts out (see api/upstream.py).
        self._gate = asyncio.Semaphore(max(1, int(os.getenv("GAANA_MAX_CONCURRENT", "4"))))
        self._pacer = Pacer()
        # After a block, stop asking Gaana for a while instead of hammering it.
        self.breaker = CircuitBreaker()
        # Remember list/search responses, and song details, so repeats cost nothing.
        self.list_cache = ResponseCache()
        self.song_cache = SongCache()

    async def _safe_request(self, method: str, url: str, cache: bool = True, **kwargs) -> dict:
        """One request to Gaana, paced, behind the circuit breaker.

        `cache=False` for responses that must not be reused (song details carry stream
        links; they have their own cache). Raises BlockedError / UpstreamUnavailable.
        """
        key = self.list_cache.key(method, url, kwargs) if cache and self.list_cache.enabled else None
        if key is not None:
            hit = self.list_cache.get(key)
            if hit is not None:
                return hit
        self.breaker.check()
        async with self._gate:
            # The breaker may have opened while this request waited for a slot.
            self.breaker.check()
            await self._pacer.wait()
            # ...or while it slept in the pacer: a request queued behind one that got a
            # 403 must not go out once its turn comes.
            self.breaker.check()
            result = await self._request_now(method, url, **kwargs)
        # "No results" is not remembered (it may be a hiccup); payloads are, even the
        # playlist ones that carry "error": "SUCCESS".
        if key is not None and isinstance(result, dict) and set(result) != {"error"}:
            self.list_cache.put(key, result)
        return result

    async def _request_now(self, method: str, url: str, **kwargs) -> dict:
        headers = {**DEFAULT_HEADERS, **(kwargs.pop("headers", None) or {})}
        try:
            async with self.aiohttp.request(method, url, headers=headers, **kwargs) as response:
                status = response.status
                if status in BLOCK_STATUSES:
                    retry_after = self.breaker.trip(status, parse_retry_after(response.headers.get("Retry-After")))
                    raise BlockedError(status, retry_after)
                if status >= 500:
                    raise UpstreamUnavailable(f"Gaana returned HTTP {status}")
                self.breaker.success()
                if status != 200:
                    return await self.errors.no_results()
                body = await response.read()
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            # Network failures are outages, not "no results".
            raise UpstreamUnavailable(f"Gaana unreachable: {type(exc).__name__}") from exc
        try:
            result = json.loads(body)
        except (ValueError, TypeError):
            return await self.errors.no_results()
        if not isinstance(result, dict):
            return await self.errors.no_results()
        return result
