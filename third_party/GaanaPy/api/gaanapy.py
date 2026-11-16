import asyncio
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
from api.errors import Errors
from api.discovery.discovery import Discovery

class GaanaPy(Songs, Albums, Artists, Trending, NewReleases, Charts, Playlists, Discovery):
    def __init__(self):
        self.aiohttp = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )
        self.api_endpoints = endpoints
        self.functions = Functions()
        self.errors = Errors()
        # Every list endpoint fans out into one Gaana request per item (a trending list
        # of 20 songs is 21 requests). Firing them all at once is what gets clients
        # rate-limited and blocked, so cap how many are in flight together.
        self._gate = asyncio.Semaphore(max(1, int(os.getenv("GAANA_MAX_CONCURRENT", "4"))))

    async def _safe_request(self, method: str, url: str, **kwargs) -> dict:
        async with self._gate:
            return await self._request_now(method, url, **kwargs)

    async def _request_now(self, method: str, url: str, **kwargs) -> dict:
        try:
            if method == "GET":
                response = await self.aiohttp.get(url, **kwargs)
            else:
                response = await self.aiohttp.post(url, **kwargs)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            # Network failures are outages, not "no results".
            raise UpstreamError(f"Gaana unreachable: {type(exc).__name__}") from exc
        # Blocked / rate-limited / server errors are outages too; surfacing them lets
        # clients show "provider unavailable" instead of a misleading empty result.
        if response.status in (401, 403, 429) or response.status >= 500:
            raise UpstreamError(f"Gaana returned HTTP {response.status}")
        try:
            if response.status != 200:
                return await self.errors.no_results()
            result = await response.json()
            if not isinstance(result, dict):
                return await self.errors.no_results()
            return result
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError):
            return await self.errors.no_results()


class UpstreamError(Exception):
    """Gaana could not be reached or refused the request (handled as HTTP 502 by app.py)."""
