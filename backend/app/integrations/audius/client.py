"""Thin HTTP client for the Audius public API (https://api.audius.co/v1).

The only place that knows Audius URLs and raw response shapes; normalisation lives in
`normalize.py`. Every response is `{"data": ...}`.
"""

import asyncio
import logging
from typing import Any

import httpx

from app.integrations.errors import ProviderNotFound, ProviderUnavailable

log = logging.getLogger(__name__)


class AudiusClient:
    def __init__(self, base_url: str, app_name: str, timeout: float = 20.0, retries: int = 2,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.base_url = base_url.rstrip("/")
        self.app_name = app_name
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=timeout, follow_redirects=True,
                                         transport=transport, headers={"Accept": "application/json"},
                                         limits=httpx.Limits(max_connections=40, max_keepalive_connections=20))
        self._retries = retries

    async def close(self) -> None:
        await self._client.aclose()

    def stream_url(self, track_id: str) -> str:
        """Public stream endpoint; it redirects to a short-lived signed MP3 URL each time
        it is opened, so the URL handed to the app does not expire itself."""
        return f"{self.base_url}/tracks/{track_id}/stream?app_name={self.app_name}"

    async def _get(self, path: str, **params: Any) -> Any:
        query = {k: v for k, v in params.items() if v is not None}
        query["app_name"] = self.app_name
        last: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                resp = await self._client.get(path, params=query)
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                last = exc
                log.warning("Audius %s failed (attempt %d): %s", path, attempt + 1, exc)
            else:
                if resp.status_code in (400, 404):
                    raise ProviderNotFound(f"Not found at Audius: {path}")
                if resp.status_code == 429 or resp.status_code >= 500:
                    last = ProviderUnavailable(f"Audius returned {resp.status_code}")
                    log.warning("Audius %s -> %s (attempt %d)", path, resp.status_code, attempt + 1)
                else:
                    resp.raise_for_status()
                    return resp.json().get("data")
            if attempt < self._retries:
                await asyncio.sleep(0.4 * (2**attempt))
        if isinstance(last, ProviderUnavailable):
            raise last
        raise ProviderUnavailable(f"Audius unreachable: {last}")

    async def health(self) -> bool:
        try:
            resp = await self._client.get("/tracks/trending", params={"limit": 1, "app_name": self.app_name},
                                          timeout=8)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    # --- endpoints -------------------------------------------------------------
    async def search_tracks(self, query: str, limit: int, sort: str | None = None) -> list[dict]:
        """`sort`: None (relevance), "popular" or "recent"."""
        return await self._get("/tracks/search", query=query, limit=limit, sort_method=sort) or []

    async def search_users(self, query: str, limit: int) -> list[dict]:
        return await self._get("/users/search", query=query, limit=limit) or []

    async def search_playlists(self, query: str, limit: int) -> list[dict]:
        return await self._get("/playlists/search", query=query, limit=limit) or []

    async def track(self, track_id: str) -> dict:
        return await self._get(f"/tracks/{track_id}")

    async def user(self, user_id: str) -> dict:
        return await self._get(f"/users/{user_id}")

    async def user_tracks(self, user_id: str, limit: int, offset: int = 0, sort: str | None = None) -> list[dict]:
        return await self._get(f"/users/{user_id}/tracks", limit=limit, offset=offset or None, sort=sort) or []

    async def user_albums(self, user_id: str, limit: int) -> list[dict]:
        return await self._get(f"/users/{user_id}/albums", limit=limit) or []

    async def related_users(self, user_id: str, limit: int) -> list[dict]:
        return await self._get(f"/users/{user_id}/related", limit=limit) or []

    async def playlist(self, playlist_id: str) -> dict:
        data = await self._get(f"/playlists/{playlist_id}")
        rows = data if isinstance(data, list) else [data]
        if not rows or not rows[0]:
            raise ProviderNotFound(f"Playlist {playlist_id} not found")
        return rows[0]

    async def playlist_tracks(self, playlist_id: str) -> list[dict]:
        return await self._get(f"/playlists/{playlist_id}/tracks") or []

    async def trending(self, limit: int, genre: str | None = None, time: str = "week") -> list[dict]:
        return await self._get("/tracks/trending", limit=limit, genre=genre, time=time) or []

    async def trending_underground(self, limit: int) -> list[dict]:
        return await self._get("/tracks/trending/underground", limit=limit) or []

    async def trending_playlists(self, limit: int) -> list[dict]:
        return await self._get("/playlists/trending", limit=limit) or []

    async def top_albums(self, limit: int) -> list[dict]:
        return await self._get("/playlists/top", type="album", limit=limit) or []
