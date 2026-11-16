"""Thin HTTP client for a running GaanaPy service.

GaanaPy is consumed over HTTP as a separate service (it is GPL-3.0 and has its own
dependencies); this module is the only place that knows GaanaPy's URLs and raw
response shapes. Normalisation into the app's schemas lives in `normalize.py`.
"""

import asyncio
import logging
from typing import Any

import httpx

from app.integrations.errors import ProviderNotFound, ProviderUnavailable

log = logging.getLogger(__name__)


class GaanaPyClient:
    def __init__(self, base_url: str, timeout: float = 30.0, retries: int = 2,
                 transport: httpx.AsyncBaseTransport | None = None):
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )
        self._retries = retries

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                resp = await self._client.get(path, params=params)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last_exc = exc
                log.warning("GaanaPy %s failed (attempt %d): %s", path, attempt + 1, exc)
            else:
                if resp.status_code == 404:
                    raise ProviderNotFound(_detail(resp))
                if resp.status_code in (400, 422):
                    # GaanaPy validates seokeys/queries strictly; treat as "nothing found".
                    raise ProviderNotFound(_detail(resp))
                if resp.status_code >= 500:
                    last_exc = ProviderUnavailable(f"GaanaPy returned {resp.status_code}: {_detail(resp)}")
                    log.warning("GaanaPy %s -> %s (attempt %d)", path, resp.status_code, attempt + 1)
                else:
                    resp.raise_for_status()
                    return resp.json()
            if attempt < self._retries:
                await asyncio.sleep(0.4 * (2**attempt))
        if isinstance(last_exc, ProviderUnavailable):
            raise last_exc
        raise ProviderUnavailable(f"Music provider unreachable: {last_exc}")

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
