import asyncio
import aiohttp
from gaanapy.songs.songs import Songs
from gaanapy.albums.albums import Albums
from gaanapy.artists.artists import Artists
from gaanapy.trending.trending import Trending
from gaanapy.newreleases.newreleases import NewReleases
from gaanapy.charts.charts import Charts
from gaanapy.playlists.playlists import Playlists
from gaanapy import endpoints
from gaanapy.functions import Functions
from gaanapy.errors import Errors
from gaanapy.discovery.discovery import Discovery

class GaanaPy(Songs, Albums, Artists, Trending, NewReleases, Charts, Playlists, Discovery):
    def __init__(self):
        self.aiohttp = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )
        self.api_endpoints = endpoints
        self.functions = Functions()
        self.errors = Errors()

    async def _safe_request(self, method: str, url: str, **kwargs) -> dict:
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
