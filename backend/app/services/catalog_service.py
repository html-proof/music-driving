"""Music catalogue access: provider calls + caching. All data comes from the provider."""

import asyncio
import logging
import re
import unicodedata
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

from pydantic import TypeAdapter

from app.config import Settings
from app.integrations.errors import ProviderError, ProviderInvalidRequest, ProviderNotFound, ProviderUnavailable
from app.integrations.gaanapy.normalize import stream_expiry
from app.integrations.provider import MusicProvider, ProviderTrack
from app.schemas.music import (
    QUALITY_BITRATE_KBPS,
    QUALITY_ORDER,
    AlbumDetail,
    AlbumSummary,
    ArtistDetail,
    ArtistSummary,
    AudioQuality,
    NewReleases,
    PlaylistDetail,
    PlaylistSummary,
    SearchResults,
    StreamInfo,
    Track,
    TrackPage,
)
from app.services.cache import Cache
from app.services.transliterate import transliterate

log = logging.getLogger(__name__)
T = TypeVar("T")

SEARCH_TYPES = ("songs", "albums", "artists", "playlists")
# Deepest search page served (GaanaPy slices one Gaana result page).
MAX_SEARCH_PAGE = 20
# Charts are fetched once at this size and sliced for /charts, Home and playlist search.
CHARTS_FETCH_SIZE = 50
# Invisible formatting characters that only get in the way of a search (BOM, bidi
# controls, word joiner). ZWJ / ZWNJ stay: they are part of Indic spelling.
_INVISIBLE = {"\ufeff", "\u200e", "\u200f", "\u202a", "\u202b", "\u202c", "\u202d", "\u202e", "\u2060",
              "\u2066", "\u2067", "\u2068", "\u2069"}


def sanitize_query(q: str) -> str:
    """Any script is a valid query: only control / invisible characters are removed,
    whitespace collapsed and the length capped at 200 characters."""
    cleaned = "".join(
        " " if unicodedata.category(ch) == "Cc" else ("" if ch in _INVISIBLE else ch)
        for ch in unicodedata.normalize("NFC", q or "")
    )
    return re.sub(r"\s+", " ", cleaned).strip()[:200].strip()


class CatalogService:
    def __init__(self, provider: MusicProvider, cache: Cache, settings: Settings, http_probe=None):
        self.provider = provider
        self.cache = cache
        self.settings = settings
        self._probe = http_probe  # async (url) -> bool, used to verify stream qualities

    async def _cached(self, key: str, ttl: int, adapter: TypeAdapter, factory: Callable[[], Awaitable[T]],
                      stale_key: str | None = None, *, remember_miss: bool = True,
                      timeout: float | None = None) -> T:
        value, _ = await self._cached_state(key, ttl, adapter, factory, stale_key, remember_miss=remember_miss,
                                            timeout=timeout)
        return value

    async def _cached_state(self, key: str, ttl: int, adapter: TypeAdapter, factory: Callable[[], Awaitable[T]],
                            stale_key: str | None = None, *, remember_miss: bool = True,
                            timeout: float | None = None) -> tuple[T, bool]:
        """Cache-first provider call that keeps Gaana traffic down. Returns (value, stale):

        * a fresh copy is served for `ttl`;
        * a "not found" answer is remembered (unless `remember_miss` is False, as for
          searches), so missing items aren't re-requested; a request the provider
          rejected as invalid is never remembered as a miss;
        * the last good copy is kept much longer and served, with stale=True, while the
          provider is unavailable (blocked / rate-limited / slower than `timeout`), so
          pages don't go blank during a block. `stale_key` lets several request shapes
          (e.g. list sizes) share that copy.
        """
        stale_key = f"stale:{stale_key or key}"
        hit = await self.cache.get(key)
        if hit is not None:
            try:
                return adapter.validate_python(hit), False
            except ValueError:
                await self.cache.delete(key)
        if remember_miss and await self.cache.get(f"miss:{key}"):
            raise ProviderNotFound("Not found")
        try:
            if timeout is None:
                value = await factory()
            else:
                try:
                    value = await asyncio.wait_for(factory(), timeout)
                except TimeoutError as exc:
                    raise ProviderUnavailable(f"Music provider did not answer within {timeout:g} s") from exc
        except ProviderInvalidRequest:
            raise
        except ProviderNotFound:
            if remember_miss:
                await self.cache.set(f"miss:{key}", True, self.settings.not_found_cache_ttl_seconds)
            raise
        except ProviderUnavailable:
            stale = await self.cache.get(stale_key)
            if stale is not None:
                try:
                    log.info("provider unavailable: serving last good copy of %s", key)
                    return adapter.validate_python(stale), True
                except ValueError:
                    pass
            raise
        dumped = adapter.dump_python(value, mode="json")
        await self.cache.set(key, dumped, ttl)
        await self.cache.set(stale_key, dumped, self.settings.stale_cache_ttl_seconds)
        return value, False

    def _known(self, song_id: str) -> ProviderTrack | None:
        known = getattr(self.provider, "known_track", None)
        return known(song_id) if known else None

    async def _remember_metadata(self, track: Track) -> None:
        await self.cache.set(f"track:{track.id}", track.model_dump(mode="json"),
                             self.settings.metadata_cache_ttl_seconds)

    def _ttl(self) -> int:
        return self.settings.catalog_cache_ttl_seconds

    def _home_ttl(self) -> int:
        return max(self.settings.home_cache_ttl_seconds, self._ttl())

    # --- discovery ---------------------------------------------------------
    async def search(self, query: str, limit: int = 10, type: str = "all", page: int = 1) -> SearchResults:
        """Search one section (`type`) or all of them. Each section runs under its own
        deadline and reports its own failure in `errors`; an empty section is not an
        error. An Indic-script query is also searched in Latin transliteration
        (`alt_query`), since Gaana's catalogue titles are mostly romanised."""
        q = sanitize_query(query)
        results = SearchResults(query=query, type=type, page=page)
        if not q:
            results.errors["query"] = "Type something to search for"
            return results
        alt = transliterate(q)
        if alt:
            alt = alt[:200].strip()  # GaanaPy rejects longer queries
        if alt == q.lower():
            alt = None
        results.alt_query = alt
        names = SEARCH_TYPES if type == "all" else (type,)
        outcomes = await asyncio.gather(*[self._search_section(name, q, alt, limit, page) for name in names],
                                        return_exceptions=True)
        paged = getattr(self.provider, "paged_search", True)
        for name, outcome in zip(names, outcomes, strict=True):
            if isinstance(outcome, ProviderNotFound):
                results.has_more[name] = False  # no results is not an error
                continue
            if isinstance(outcome, BaseException):
                results.errors[name] = _error_message(outcome)
                results.has_more[name] = False
                continue
            setattr(results, name, outcome)
            results.has_more[name] = paged and len(outcome) == limit and page < MAX_SEARCH_PAGE
        return results

    async def _search_section(self, section: str, q: str, alt: str | None, limit: int, page: int) -> list:
        timeout = self.settings.search_section_timeout_seconds
        try:
            if alt is None:
                return await asyncio.wait_for(self._search_term(section, q, limit, page), timeout)
            # Latin form first (Gaana matches it far better), then the original script.
            outcomes = await asyncio.wait_for(
                asyncio.gather(self._search_term(section, alt, limit, page),
                               self._search_term(section, q, limit, page), return_exceptions=True),
                timeout)
        except TimeoutError as exc:
            raise ProviderUnavailable(f"{section} search took longer than {timeout:g} s") from exc
        merged: list = []
        seen: set[str] = set()
        failures = [o for o in outcomes if isinstance(o, BaseException) and not isinstance(o, ProviderNotFound)]
        for outcome in outcomes:
            if isinstance(outcome, BaseException):
                continue
            for item in outcome:
                if item.id not in seen:
                    seen.add(item.id)
                    merged.append(item)
        if not merged and failures:
            raise failures[0]
        if failures:
            log.info("%s search: one query form failed (%s); returning the other's results", section, failures[0])
        if not merged:
            raise ProviderNotFound("No results")
        return merged[:limit]

    async def _search_term(self, section: str, term: str, limit: int, page: int) -> list:
        adapters: dict[str, Any] = {"songs": list[Track], "albums": list[AlbumSummary],
                                    "artists": list[ArtistSummary], "playlists": list[PlaylistSummary]}
        if section == "playlists":
            return await self._search_playlists(term, limit, page)
        call = {"songs": self.provider.search_songs, "albums": self.provider.search_albums,
                "artists": self.provider.search_artists}[section]
        # Never remember a search miss: an empty answer during a partial block must not
        # hide songs that exist.
        return await self._cached(f"search:{section}:{term.lower()}:{limit}:{page}",
                                  self.settings.search_cache_ttl_seconds, TypeAdapter(adapters[section]),
                                  lambda: call(term, limit, page), remember_miss=False)

    async def _search_playlists(self, q: str, limit: int, page: int = 1) -> list[PlaylistSummary]:
        search = getattr(self.provider, "search_playlists", None)
        if search is not None:
            return await self._cached(f"search:playlists:{q.lower()}:{limit}:{page}",
                                      self.settings.search_cache_ttl_seconds, TypeAdapter(list[PlaylistSummary]),
                                      lambda: search(q, limit, page), remember_miss=False)
        # GaanaPy has no playlist search; match against the live chart playlists instead.
        words = q.lower().split()
        charts = await self.charts(CHARTS_FETCH_SIZE)
        matches = [p for p in charts if all(w in p.title.lower() for w in words)]
        return matches[(page - 1) * limit: page * limit]

    async def artist_by_name(self, name: str) -> ArtistSummary:
        """The provider's artist with exactly this name (case-insensitive), from a
        one-row artist search; kept for a day. Raises ProviderNotFound otherwise."""
        wanted = name.strip().casefold()

        async def load() -> ArtistSummary:
            rows = await self.provider.search_artists(name.strip(), 1)
            match = next((a for a in rows if a.name.strip().casefold() == wanted), None)
            if match is None:
                raise ProviderNotFound(f"No artist named {name}")
            return match

        return await self._cached(f"artist-name:{wanted}", self.settings.metadata_cache_ttl_seconds,
                                  TypeAdapter(ArtistSummary), load,
                                  timeout=self.settings.home_section_timeout_seconds)

    async def song(self, song_id: str) -> Track:
        """Song metadata. Served from the long-lived metadata cache or from a list the
        provider already returned whenever possible (lyrics need only title/artist)."""
        hit = await self.cache.get(f"track:{song_id}")
        if hit:
            try:
                return Track.model_validate(hit)
            except ValueError:
                await self.cache.delete(f"track:{song_id}")
        known = self._known(song_id)
        if known:
            await self._remember_metadata(known.track)
            return known.track
        return (await self._song_with_streams(song_id)).track

    async def _song_with_streams(self, song_id: str, fresh: bool = False) -> ProviderTrack:
        key = f"song:{song_id}"
        if not fresh:
            hit = await self.cache.get(key)
            if hit:
                streams = {AudioQuality(q): u for q, u in hit["streams"].items()}
                return ProviderTrack(Track.model_validate(hit["track"]), streams)
            # Listed songs carry their stream URLs: no second lookup needed.
            known = self._known(song_id)
            if known and known.streams and not self._expired(known.streams):
                await self._store_song(key, known)
                return known
        if await self.cache.get(f"miss:{key}"):
            raise ProviderNotFound(f"Song {song_id} not found")
        try:
            pt = await self.provider.get_song(song_id)
        except ProviderInvalidRequest:
            raise  # the provider rejected the id format: not proof the song is missing
        except ProviderNotFound:
            await self.cache.set(f"miss:{key}", True, self.settings.not_found_cache_ttl_seconds)
            raise
        await self._store_song(key, pt)
        return pt

    async def _store_song(self, key: str, pt: ProviderTrack) -> None:
        await self.cache.set(
            key,
            {"track": pt.track.model_dump(mode="json"), "streams": {q.value: u for q, u in pt.streams.items()}},
            self._stream_cache_ttl(pt.streams),
        )
        await self._remember_metadata(pt.track)

    def _stream_cache_ttl(self, streams: dict[AudioQuality, str]) -> int:
        """Never cache past the stream token's own expiry (minus a safety margin)."""
        ttl = self._ttl()
        for url in streams.values():
            exp = stream_expiry(url)
            if exp:
                remaining = int((exp - datetime.now(UTC)).total_seconds()) - self.settings.stream_refresh_margin_seconds
                ttl = min(ttl, max(remaining, 0))
        return ttl

    async def album(self, album_id: str) -> AlbumDetail:
        return await self._cached(f"album:{album_id}", self._ttl(), TypeAdapter(AlbumDetail),
                                  lambda: self.provider.get_album(album_id))

    async def similar_albums(self, album_numeric_id: str, limit: int = 10) -> list[AlbumSummary]:
        return await self._cached(f"album-similar:{album_numeric_id}:{limit}", self._ttl(),
                                  TypeAdapter(list[AlbumSummary]),
                                  lambda: self.provider.similar_albums(album_numeric_id, limit))

    async def artist(self, artist_id: str, limit: int = 10) -> ArtistDetail:
        async def load() -> ArtistDetail:
            detail = await self.provider.get_artist(artist_id, limit)
            if detail.numeric_id:
                try:
                    detail.similar_artists = await self.provider.similar_artists(detail.numeric_id, 10)
                except ProviderError as exc:
                    log.info("similar artists unavailable for %s: %s", artist_id, exc)
            return detail

        return await self._cached(f"artist:{artist_id}:{limit}", self._ttl(), TypeAdapter(ArtistDetail), load)

    async def similar_artists_for(self, artist_numeric_id: str, limit: int = 10) -> list[ArtistSummary]:
        return await self._cached(f"artist-similar:{artist_numeric_id}:{limit}", self._ttl(),
                                  TypeAdapter(list[ArtistSummary]),
                                  lambda: self.provider.similar_artists(artist_numeric_id, limit))

    async def artist_tracks(self, artist_numeric_id: str, limit: int = 20, page: int = 1) -> TrackPage:
        return await self._cached(f"artist-tracks:{artist_numeric_id}:{limit}:{page}", self._ttl(),
                                  TypeAdapter(TrackPage),
                                  lambda: self.provider.artist_tracks(artist_numeric_id, limit, page))

    def _list_size(self, limit: int | None) -> int:
        """Language lists are fetched at one standard size (the home row) and trimmed.

        Each listed song costs a Gaana request, so the home feed, "Made for you" and
        /trending asking for 12, 20 or 30 songs of the same language must not each
        fetch their own copy: that multiplied traffic until Gaana blocked us and the
        regional rows disappeared.
        """
        size = self.settings.home_section_size
        return size if limit is None or limit <= size else limit

    async def trending(self, language: str, limit: int | None = None) -> list[Track]:
        return (await self.trending_state(language, limit))[0]

    async def trending_state(self, language: str, limit: int | None = None,
                             timeout: float | None = None) -> tuple[list[Track], bool]:
        """Trending songs of a language and whether they are a stale (last good) copy."""
        n = self._list_size(limit)
        lang = language.strip().lower()
        tracks, stale = await self._cached_state(f"trending:{lang}:{n}", self._home_ttl(), TypeAdapter(list[Track]),
                                                 lambda: self.provider.trending(language, n),
                                                 stale_key=f"trending:{lang}", timeout=timeout)
        return tracks[: limit or n], stale

    async def new_releases(self, language: str, limit: int | None = None) -> NewReleases:
        return (await self.new_releases_state(language, limit))[0]

    async def new_releases_state(self, language: str, limit: int | None = None,
                                 timeout: float | None = None) -> tuple[NewReleases, bool]:
        """New tracks and albums of a language (up to `limit` of each)."""
        n = self._list_size(limit)
        lang = language.strip().lower()
        new, stale = await self._cached_state(f"new:{lang}:{n}", self._home_ttl(), TypeAdapter(NewReleases),
                                              lambda: self.provider.new_releases(language, n),
                                              stale_key=f"new:{lang}", timeout=timeout)
        k = limit or n
        return new.model_copy(update={"tracks": new.tracks[:k], "albums": new.albums[:k]}), stale

    async def charts(self, limit: int = 20) -> list[PlaylistSummary]:
        return (await self.charts_state(limit))[0]

    async def charts_state(self, limit: int = 20, timeout: float | None = None) -> tuple[list[PlaylistSummary], bool]:
        """Chart playlists. One cached fetch serves /charts, Home and playlist search."""
        size = max(limit, CHARTS_FETCH_SIZE)
        key = "charts" if size == CHARTS_FETCH_SIZE else f"charts:{size}"
        charts, stale = await self._cached_state(key, self._home_ttl(), TypeAdapter(list[PlaylistSummary]),
                                                 lambda: self.provider.charts(size), stale_key="charts",
                                                 timeout=timeout)
        return charts[:limit], stale

    async def playlist(self, playlist_id: str) -> PlaylistDetail:
        async def load() -> PlaylistDetail:
            detail = await self.provider.get_playlist(playlist_id)
            try:  # borrow title/artwork from the chart listing when this playlist is a chart
                meta = next((p for p in await self.charts(CHARTS_FETCH_SIZE) if p.id == playlist_id), None)
            except ProviderError:
                meta = None
            if meta:
                detail = PlaylistDetail(**meta.model_dump(), tracks=detail.tracks)
            elif detail.tracks:
                detail.artwork = detail.tracks[0].artwork
            return detail

        return await self._cached(f"playlist:{playlist_id}", self._ttl(), TypeAdapter(PlaylistDetail), load)

    # --- streaming -----------------------------------------------------------
    async def stream(self, song_id: str, quality: AudioQuality) -> StreamInfo:
        pt = await self._song_with_streams(song_id)
        if not pt.streams or self._expired(pt.streams):
            pt = await self._song_with_streams(song_id, fresh=True)
        if not pt.streams:
            raise ProviderNotFound("The provider did not return a playable stream for this song")

        available = [q for q in QUALITY_ORDER if q in pt.streams]
        # Try the requested quality first, then step down, then up.
        idx = QUALITY_ORDER.index(quality)
        candidates = [q for q in QUALITY_ORDER[idx:] + list(reversed(QUALITY_ORDER[:idx])) if q in pt.streams]
        chosen: AudioQuality | None = None
        for q in candidates:
            if await self._verify(song_id, q, pt.streams[q]):
                chosen = q
                break
        if chosen is None:
            raise ProviderUnavailable("None of the provider's stream URLs for this song responded")
        url = pt.streams[chosen]
        return StreamInfo(
            song_id=song_id,
            quality=chosen,
            requested_quality=quality,
            url=url,
            format=getattr(self.provider, "stream_format", "hls"),
            bitrate_kbps=QUALITY_BITRATE_KBPS[chosen],
            expires_at=stream_expiry(url),
            available_qualities=available,
        )

    def _expired(self, streams: dict[AudioQuality, str]) -> bool:
        margin = timedelta(seconds=self.settings.stream_refresh_margin_seconds)
        for url in streams.values():
            exp = stream_expiry(url)
            if exp and exp - margin <= datetime.now(UTC):
                return True
        return False

    async def _verify(self, song_id: str, quality: AudioQuality, url: str) -> bool:
        """GaanaPy derives some quality URLs by string substitution, so check they exist.
        Providers with a single stream per track opt out (`verify_streams = False`)."""
        if (not self.settings.verify_stream_quality or self._probe is None
                or not getattr(self.provider, "verify_streams", True)):
            return True
        key = f"streamcheck:{song_id}:{quality.value}"
        hit = await self.cache.get(key)
        if hit is not None:
            return bool(hit)
        ok = await self._probe(url)
        await self.cache.set(key, ok, self._stream_cache_ttl({quality: url}) if ok else 300)
        return ok


def _error_message(exc: BaseException) -> str:
    if isinstance(exc, ProviderUnavailable):
        return "Music provider is currently unavailable"
    if isinstance(exc, ProviderError):
        return "Music provider error"
    log.exception("unexpected search failure", exc_info=exc)
    return "Unexpected error"
