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

from app.integrations.errors import ProviderError, ProviderInvalidRequest, ProviderNotFound, ProviderUnavailable

log = logging.getLogger(__name__)

# Longest wait GaanaPy's `retry_after` can impose on us (guards against a garbage value).
_MAX_RETRY_AFTER_SECONDS = 3600


class GaanaPyClient:
    """Every request to Gaana goes through here, so this is where load is controlled:

    * Identical requests already in flight share one call (single-flight).
    * Retries only cover GaanaPy itself being unreachable (connection refused / connect
      timeout). A read timeout is never retried: GaanaPy already has the request and is
      working on it, so a retry would only send the same Gaana traffic again.
    * GaanaPy's answers map to errors as follows:
        503 {"error": "blocked", "retry_after": n}  Gaana refused us (401/403/429) or
            GaanaPy's own circuit breaker is open -> ProviderUnavailable and a cooldown
            (at least `retry_after`) that doubles on each repeat block, up to a maximum.
            During the cooldown every call fails fast and nothing reaches Gaana. After
            it, a single probe request decides: success ends the cooldown, another
            refusal starts a longer one. Answers to requests that were already in flight
            when the cooldown started or ended belong to the earlier period: a refusal
            only extends the current cooldown to its `retry_after` (it never doubles it,
            so one burst of parallel 503s counts as one block) and a success does not end
            it.
        502 / 504  network error or 5xx from Gaana -> ProviderUnavailable for this call
            only (no cooldown: Gaana did not refuse us).
        500  a bug inside GaanaPy -> ProviderError (logged, no cooldown).
        404  nothing found -> ProviderNotFound.
        400 / 422  GaanaPy rejected the parameters -> ProviderInvalidRequest (never
            remembered as "not found").
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
        # Bumped whenever a cooldown starts or ends; each request remembers the value it
        # was sent under, so late answers from an earlier period are recognised.
        self._period = 0
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
        except asyncio.CancelledError:
            # This caller gave up (e.g. a section deadline); others sharing the call did
            # not, so they get a provider error instead of a foreign cancellation.
            future.set_exception(ProviderUnavailable("Music provider request was cancelled"))
            future.exception()
            raise
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
            return await self._request(path, params, self._period)
        finally:
            if probe:
                self._probing = False

    async def _request(self, path: str, params: dict[str, Any] | None, period: int) -> Any:
        last_exc: Exception | None = None
        for attempt in range(self._retries + 1):
            try:
                resp = await self._client.get(path, params=params)
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # GaanaPy itself is unreachable: no Gaana traffic was sent, so retry.
                last_exc = exc
                log.warning("GaanaPy %s failed (attempt %d): %s", path, attempt + 1, exc)
                if attempt < self._retries:
                    await asyncio.sleep(0.4 * (2**attempt))
                continue
            except (httpx.TransportError, httpx.TimeoutException) as exc:
                # GaanaPy got the request (read timeout, dropped connection) and may still
                # be calling Gaana for it: a retry would send that traffic again.
                log.warning("GaanaPy %s failed: %r", path, exc)
                raise ProviderUnavailable(f"Music provider did not answer: {type(exc).__name__}") from exc
            return self._handle(path, resp, period)
        raise ProviderUnavailable(f"Music provider unreachable: {last_exc}")

    def _handle(self, path: str, resp: httpx.Response, period: int) -> Any:
        status = resp.status_code
        if status in (503, 429):
            # Gaana refused us, or GaanaPy's own breaker is open. Retrying would only
            # extend the block: back off, for at least as long as GaanaPy asks.
            self._start_cooldown(_retry_after(resp), period)
            log.warning("GaanaPy %s -> %s (%s); not calling Gaana for %.0f s", path, status, _detail(resp),
                        self._blocked_until - self._clock())
            raise ProviderUnavailable(f"Music provider is blocking requests ({_detail(resp)})")
        if status == 500:
            log.error("GaanaPy %s -> 500 (internal error: %s)", path, _detail(resp))
            raise ProviderError("Music provider error")
        if status >= 500:
            # Gaana failed or timed out on its side: this call fails, nothing else does.
            log.warning("GaanaPy %s -> %s: %s", path, status, _detail(resp))
            raise ProviderUnavailable(f"GaanaPy returned {status}: {_detail(resp)}")
        self._end_cooldown(period)
        if status == 404:
            raise ProviderNotFound(_detail(resp))
        if status in (400, 422):
            raise ProviderInvalidRequest(_detail(resp))
        resp.raise_for_status()
        return resp.json()

    def _start_cooldown(self, retry_after: float, period: int) -> None:
        now = self._clock()
        if period != self._period:
            # Sent before the current cooldown started (a parallel request of the same
            # burst) or before a probe ended the last one: not a new block.
            if self._cooldown:
                self._blocked_until = max(self._blocked_until, now + retry_after)
            return
        self._cooldown = min(self._cooldown * 2, self._cooldown_max) if self._cooldown else self._cooldown_base
        self._period += 1
        self._blocked_until = max(self._blocked_until, now + max(self._cooldown, retry_after))

    def _end_cooldown(self, period: int) -> None:
        if not self._cooldown or period != self._period:
            return  # no cooldown, or a late answer to a request sent before it started
        log.info("Music provider answering again; cooldown over")
        self._cooldown = 0.0
        self._period += 1
        self._blocked_until = 0.0

    async def health(self) -> bool:
        try:
            resp = await self._client.get("/health", timeout=5)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False

    # --- endpoints -------------------------------------------------------
    # Search pages are 1-based slices of Gaana's first result page (GaanaPy caps page at 20).
    async def search_songs(self, query: str, limit: int, page: int = 1) -> list[dict]:
        return await self._get("/songs/search/", {"query": query, "limit": limit, "page": page})

    async def search_albums(self, query: str, limit: int, page: int = 1) -> list[dict]:
        return await self._get("/albums/search/", {"query": query, "limit": limit, "page": page})

    async def search_artists(self, query: str, limit: int, page: int = 1) -> list[dict]:
        return await self._get("/artists/search/", {"query": query, "limit": limit, "page": page})

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
    except ValueError:
        return resp.text[:200]
    if not isinstance(body, dict):
        return str(body)[:200]
    parts = [str(body[k]) for k in ("error", "detail", "upstream_status") if body.get(k) not in (None, "")]
    return ": ".join(parts) if parts else str(body)[:200]


def _retry_after(resp: httpx.Response) -> float:
    """Seconds GaanaPy asks us to wait (JSON `retry_after`, else the Retry-After header)."""
    value: Any = None
    try:
        body = resp.json()
        if isinstance(body, dict):
            value = body.get("retry_after")
    except ValueError:
        pass
    if value is None:
        value = resp.headers.get("Retry-After")
    try:
        return min(max(float(value), 0.0), _MAX_RETRY_AFTER_SECONDS)
    except (TypeError, ValueError):
        return 0.0
