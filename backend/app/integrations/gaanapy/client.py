"""Thin HTTP client for a running GaanaPy service.

GaanaPy is consumed over HTTP as a separate service (it is GPL-3.0 and has its own
dependencies); this module is the only place that knows GaanaPy's URLs and raw
response shapes. Normalisation into the app's schemas lives in `normalize.py`.
"""

import asyncio
import logging
import time
from typing import Any

import httpx

from app.integrations.errors import ProviderNotFound, ProviderUnavailable

log = logging.getLogger(__name__)


class GaanaPyClient:
    """Every request to Gaana goes through here, so this is where load is controlled:

    * Identical requests already in flight share one call (single-flight).
    * Retries only cover GaanaPy itself being unreachable (local network hiccup).
    * When Gaana refuses a request (GaanaPy answers 5xx: blocked / rate-limited), the
      client stops calling for a cooldown that doubles on each repeat block, up to a
      maximum. During the cooldown every call fails fast with ProviderUnavailable and
      nothing reaches Gaana. After it, a single probe request decides: success ends
      the cooldown, another refusal starts a longer one.
    """

    def __init__(self, base_url: str, timeout: float = 30.0, retries: int = 2,
                 transport: httpx.AsyncBaseTransport | None = None,
                 block_cooldown_seconds: float = 60.0, block_cooldown_max_seconds: float = 600.0,
                 clock=time.monotonic):
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )
        self._retries = retries
        self._cooldown_base = block_cooldown_seconds
        self._cooldown_max = block_cooldown_max_seconds
        self._clock = clock
        self._blocked_until = 0.0
        self._cooldown = 0.0
        self._probing = False
        self._in_flight: dict[tuple, asyncio.Future] = {}

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def blocked(self) -> bool:
        """True while Gaana is being left alone after refusing us."""
        return self._clock() < self._blocked_until

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        key = (path, tuple(sorted((params or {}).items())))
        shared = self._in_flight.get(key)
        if shared is not None:
            return await asyncio.shield(shared)
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._in_flight[key] = future
        try:
            result = await self._get_uncoalesced(path, params)
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()  # mark retrieved: nobody else may be waiting
            raise
        else:
            future.set_result(result)
            return result
        finally:
            self._in_flight.pop(key, None)

    async def _get_uncoalesced(self, path: str, params: dict[str, Any] | None) -> Any:
        if self.blocked:
            raise ProviderUnavailable("Music provider is blocking requests; backing off")
        if self._cooldown and self._probing:
            # Cooldown just ended and one probe is already testing the water.
            raise ProviderUnavailable("Music provider is blocking requests; backing off")
        probe = bool(self._cooldown)
        self._probing = probe
        try:
            return await self._request(path, params)
        finally:
            if probe:
                self._probing = False

    async def _request(self, path: str, params: dict[str, Any] | None) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                resp = await self._client.get(path, params=params)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                # GaanaPy itself is unreachable: no Gaana traffic was sent, so retry.
                last_exc = exc
                log.warning("GaanaPy %s failed (attempt %d): %s", path, attempt + 1, exc)
                if attempt < self._retries:
                    await asyncio.sleep(0.4 * (2**attempt))
                continue
            if resp.status_code >= 500:
                # Gaana refused (GaanaPy reports blocks / rate limits as 502). Retrying
                # would only extend the block: back off instead.
                self._start_cooldown()
                log.warning("GaanaPy %s -> %s; not calling Gaana for %.0f s", path, resp.status_code,
                            self._cooldown)
                raise ProviderUnavailable(f"GaanaPy returned {resp.status_code}: {_detail(resp)}")
            self._end_cooldown()
            if resp.status_code == 404:
                raise ProviderNotFound(_detail(resp))
            if resp.status_code in (400, 422):
                # GaanaPy validates seokeys/queries strictly; treat as "nothing found".
                raise ProviderNotFound(_detail(resp))
            resp.raise_for_status()
            return resp.json()
        raise ProviderUnavailable(f"Music provider unreachable: {last_exc}")

    def _start_cooldown(self) -> None:
        self._cooldown = min(self._cooldown * 2, self._cooldown_max) if self._cooldown else self._cooldown_base
        self._blocked_until = self._clock() + self._cooldown

    def _end_cooldown(self) -> None:
        if self._cooldown:
            log.info("Music provider answering again; cooldown over")
        self._cooldown = 0.0
        self._blocked_until = 0.0

    async def health(self) -> bool:
        try:
            resp = await self._client.get("/health", timeout=5)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    # --- endpoints -------------------------------------------------------
    async def search_songs(self, query: str, limit: int) -> list[dict]:
        return await self._get("/songs/search/", {"query": query, "limit": limit})

    async def search_albums(self, query: str, limit: int) -> list[dict]:
        return await self._get("/albums/search/", {"query": query, "limit": limit})

    async def search_artists(self, query: str, limit: int) -> list[dict]:
        return await self._get("/artists/search/", {"query": query, "limit": limit})

    async def song_info(self, seokey: str) -> list[dict]:
        return await self._get("/songs/info/", {"seokey": seokey})

    async def album_info(self, seokey: str) -> list[dict]:
        return await self._get("/albums/info/", {"seokey": seokey})

    async def similar_albums(self, album_id: str, limit: int) -> list[dict]:
        return await self._get("/albums/similar/", {"album_id": album_id, "limit": limit})

    async def artist_info(self, seokey: str, limit: int, page: int = 1) -> list[dict]:
        return await self._get("/artists/info/", {"seokey": seokey, "limit": limit, "page": page})

    async def artist_tracks(self, artist_id: str, limit: int, page: int) -> dict:
        return await self._get("/artists/tracks/", {"artist_id": artist_id, "limit": limit, "page": page})

    async def similar_artists(self, artist_id: str, limit: int) -> list[dict]:
        return await self._get("/artists/similar/", {"artist_id": artist_id, "limit": limit})

    async def trending(self, language: str, limit: int) -> list[dict]:
        return await self._get("/trending", {"language": language, "limit": limit})

    async def new_releases(self, language: str, limit: int) -> dict:
        return await self._get("/newreleases", {"language": language, "limit": limit})

    async def charts(self, limit: int) -> list[dict]:
        return await self._get("/charts", {"limit": limit})

    async def playlist_info(self, seokey: str) -> list[dict]:
        return await self._get("/playlists/info/", {"seokey": seokey})


def _detail(resp: httpx.Response) -> str:
    try:
        body = resp.json()
        return str(body.get("detail") or body.get("error") or body)
    except ValueError:
        return resp.text[:200]
