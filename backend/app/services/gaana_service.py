"""GaanaPy integration: the only module that talks to Gaana.

GaanaPy (https://github.com/ZingyTomato/GaanaPy, GPL-3.0) is vendored in
`backend/vendor/gaanapy` and used in-process as a library, so the deployment is a single
FastAPI service. This wrapper adds what the library lacks: a shared HTTP session with
bounded concurrency, URL-encoding of search terms, caching, and conversion of GaanaPy's
`{"error": ...}` results into proper exceptions.

Every method returns GaanaPy's raw dictionaries; `music_service` normalises them.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import aiohttp

from app.config import Settings
from app.utils.cache import TTLCache
from app.utils.errors import NotFound, ProviderUnavailable
from app.utils.normalize import records, stream_expiry, stream_urls

_VENDOR = Path(__file__).resolve().parents[2] / "vendor"
if str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))

from gaanapy import endpoints as gaana_endpoints  # noqa: E402
from gaanapy.errors import Errors  # noqa: E402
from gaanapy.functions import Functions  # noqa: E402
from gaanapy.gaanapy import GaanaPy, UpstreamError  # noqa: E402

log = logging.getLogger(__name__)

_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
}


class _GaanaClient(GaanaPy):
    """GaanaPy with an injected session and a cap on concurrent upstream requests.

    GaanaPy fans out one request per song (search -> N song lookups); without the cap a
    single search could open dozens of connections to Gaana at once.
    """

    def __init__(self, session: aiohttp.ClientSession, concurrency: int):
        # Deliberately not calling GaanaPy.__init__, which creates its own session.
        self.aiohttp = session
        self.api_endpoints = gaana_endpoints
        self.functions = Functions()
        self.errors = Errors()
        self._semaphore = asyncio.Semaphore(max(1, concurrency))
        self.upstream_requests = 0

    async def _safe_request(self, method: str, url: str, **kwargs) -> dict:
        async with self._semaphore:
            self.upstream_requests += 1
            return await super()._safe_request(method, url, **kwargs)


def _is_error(result: Any) -> bool:
    return isinstance(result, dict) and "error" in result


class GaanaService:
    def __init__(self, settings: Settings, cache: TTLCache, client: Optional[GaanaPy] = None):
        self.settings = settings
        self.cache = cache
        self._client = client
        self._session: Optional[aiohttp.ClientSession] = None

    async def start(self) -> None:
        if self._client is None:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.settings.upstream_timeout_seconds),
                headers=_BROWSER_HEADERS,
            )
            self._client = _GaanaClient(self._session, self.settings.upstream_concurrency)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()

    @property
    def client(self) -> GaanaPy:
        if self._client is None:
            raise RuntimeError("GaanaService.start() was not called")
        return self._client

    @property
    def upstream_requests(self) -> int:
        return getattr(self._client, "upstream_requests", 0)

    # --- plumbing ----------------------------------------------------------------------
    async def _call(self, what: str, coro) -> Any:
        try:
            return await coro
        except UpstreamError as exc:
            log.warning("gaana unavailable during %s: %s", what, exc)
            raise ProviderUnavailable("The music provider is unavailable right now. Please try again shortly.") from exc
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            log.warning("gaana network error during %s: %r", what, exc)
            raise ProviderUnavailable("The music provider could not be reached.") from exc

    async def _cached(self, key: str, what: str, factory, ttl: float, empty_ttl: Optional[float] = None) -> Any:
        """Cache successful results for `ttl`; "no results" for a short time, as a NotFound."""
        empty_ttl = self.settings.cache_ttl_empty if empty_ttl is None else empty_ttl

        async def load():
            result = await self._call(what, factory())
            return {"error": result["error"]} if _is_error(result) else {"ok": result}

        def ttl_for(wrapped):
            return empty_ttl if "error" in wrapped else ttl

        wrapped = await self.cache.get_or_load(key, load, ttl_for)
        if "error" in wrapped:
            raise NotFound(f"No results for {what}")
        return wrapped["ok"]

    def _remember_songs(self, raw_tracks: Any) -> None:
        """Seed the song cache from any list of full song records (they carry stream URLs)."""
        for raw in records(raw_tracks):
            self.cache.set(f"song:{raw['seokey']}", {"ok": raw}, self._song_ttl(raw))

    def _song_ttl(self, raw: Dict) -> float:
        """Keep a song record only while its stream URLs are comfortably valid."""
        urls = stream_urls(raw)
        if not urls:
            return self.settings.cache_ttl_empty
        expiry = stream_expiry(next(iter(urls.values())))
        if expiry is None:
            return 600
        remaining = expiry.timestamp() - time.time() - self.settings.stream_refresh_margin
        return max(0.0, min(float(self.settings.cache_ttl_catalog), remaining))

    # --- search ------------------------------------------------------------------------
    async def search_songs(self, q: str, limit: int) -> List[Dict]:
        key = f"search:songs:{q.lower()}:{limit}"
        try:
            result = await self._cached(key, f"songs matching '{q}'",
                                        lambda: self.client.search_songs(quote(q, safe=""), limit),
                                        self.settings.cache_ttl_search)
        except NotFound:
            return []
        self._remember_songs(result)
        return records(result)

    async def search_albums(self, q: str, limit: int) -> List[Dict]:
        key = f"search:albums:{q.lower()}:{limit}"
        try:
            result = await self._cached(key, f"albums matching '{q}'",
                                        lambda: self.client.search_albums(quote(q, safe=""), limit),
                                        self.settings.cache_ttl_search)
        except NotFound:
            return []
        return records(result)

    async def search_artists(self, q: str, limit: int) -> List[Dict]:
        key = f"search:artists:{q.lower()}:{limit}"
        try:
            result = await self._cached(key, f"artists matching '{q}'",
                                        lambda: self.client.search_artists(quote(q, safe=""), limit),
                                        self.settings.cache_ttl_search)
        except NotFound:
            return []
        return records(result)

    # --- songs -------------------------------------------------------------------------
    async def song(self, seokey: str, fresh: bool = False) -> Dict:
        key = f"song:{seokey}"
        if fresh:
            self.cache.delete(key)

        async def load():
            result = await self._call(f"song '{seokey}'", self.client.get_track_info([seokey]))
            items = records(result)
            return {"ok": items[0]} if items else {"error": "not found"}

        wrapped = await self.cache.get_or_load(
            key, load, lambda w: self._song_ttl(w["ok"]) if "ok" in w else self.settings.cache_ttl_empty)
        if "error" in wrapped:
            raise NotFound(f"Song '{seokey}' was not found")
        return wrapped["ok"]

    # --- albums ------------------------------------------------------------------------
    async def album(self, seokey: str) -> Dict:
        result = await self._cached(f"album:{seokey}", f"album '{seokey}'",
                                    lambda: self.client.get_album_info([seokey], True),
                                    self.settings.cache_ttl_catalog)
        items = records(result)
        if not items:
            raise NotFound(f"Album '{seokey}' was not found")
        self._remember_songs(items[0].get("tracks"))
        return items[0]

    async def similar_albums(self, album_id: str, limit: int) -> List[Dict]:
        try:
            result = await self._cached(f"album-similar:{album_id}:{limit}", "similar albums",
                                        lambda: self.client.get_similar_albums(album_id, limit),
                                        self.settings.cache_ttl_catalog)
        except NotFound:
            return []
        return records(result)

    # --- artists -----------------------------------------------------------------------
    async def artist(self, seokey: str, top_tracks: int = 10) -> Dict:
        result = await self._cached(f"artist:{seokey}:{top_tracks}", f"artist '{seokey}'",
                                    lambda: self.client.get_artist_info([seokey], True, top_tracks, 1),
                                    self.settings.cache_ttl_catalog)
        items = records(result)
        if not items:
            raise NotFound(f"Artist '{seokey}' was not found")
        self._remember_songs(items[0].get("top_tracks"))
        return items[0]

    async def artist_tracks(self, artist_id: str, limit: int, page: int) -> Dict:
        try:
            result = await self._cached(f"artist-tracks:{artist_id}:{limit}:{page}", "artist tracks",
                                        lambda: self.client.get_artist_tracks(artist_id, limit, page),
                                        self.settings.cache_ttl_catalog)
        except NotFound:
            return {"tracks": [], "total": 0}
        self._remember_songs(result.get("tracks"))
        return result

    async def similar_artists(self, artist_id: str, limit: int) -> List[Dict]:
        try:
            result = await self._cached(f"artist-similar:{artist_id}:{limit}", "similar artists",
                                        lambda: self.client.get_similar_artists(artist_id, limit),
                                        self.settings.cache_ttl_catalog)
        except NotFound:
            return []
        return records(result)

    # --- feeds -------------------------------------------------------------------------
    async def trending(self, language: str, limit: int) -> List[Dict]:
        try:
            result = await self._cached(f"trending:{language}:{limit}", f"trending {language} songs",
                                        lambda: self.client.get_trending(language, limit),
                                        self.settings.cache_ttl_feed)
        except NotFound:
            return []
        self._remember_songs(result)
        return records(result)

    async def new_releases(self, language: str, limit: int) -> Dict[str, List[Dict]]:
        try:
            result = await self._cached(f"new-releases:{language}:{limit}", f"new {language} releases",
                                        lambda: self.client.get_new_releases(language, limit),
                                        self.settings.cache_ttl_feed)
        except NotFound:
            return {"tracks": [], "albums": []}
        self._remember_songs(result.get("tracks"))
        return {"tracks": records(result.get("tracks")), "albums": records(result.get("albums"))}

    async def charts(self, limit: int) -> List[Dict]:
        try:
            result = await self._cached(f"charts:{limit}", "charts",
                                        lambda: self.client.get_charts(limit),
                                        self.settings.cache_ttl_feed)
        except NotFound:
            return []
        return records(result)

    async def playlist(self, seokey: str) -> List[Dict]:
        result = await self._cached(f"playlist:{seokey}", f"playlist '{seokey}'",
                                    lambda: self.client.get_playlist_info(seokey),
                                    self.settings.cache_ttl_feed)
        self._remember_songs(result)
        items = records(result)
        if not items:
            raise NotFound(f"Playlist '{seokey}' has no playable tracks")
        return items
