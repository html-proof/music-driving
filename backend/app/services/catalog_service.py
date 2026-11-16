"""Music catalogue access: provider calls + caching. All data comes from the provider."""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import TypeVar

from pydantic import TypeAdapter

from app.config import Settings
from app.integrations.errors import ProviderError, ProviderNotFound, ProviderUnavailable
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

log = logging.getLogger(__name__)
T = TypeVar("T")

# GaanaPy rejects anything outside this character set with a 422.
_QUERY_ALLOWED = re.compile(r"[^a-zA-Z0-9\s\-'.&]")


def sanitize_query(q: str) -> str:
    return re.sub(r"\s+", " ", _QUERY_ALLOWED.sub(" ", q)).strip()[:200]


class CatalogService:
    def __init__(self, provider: MusicProvider, cache: Cache, settings: Settings, http_probe=None):
        self.provider = provider
        self.cache = cache
        self.settings = settings
        self._probe = http_probe  # async (url) -> bool, used to verify stream qualities

    async def _cached(self, key: str, ttl: int, adapter: TypeAdapter, factory: Callable[[], Awaitable[T]],
                      stale_key: str | None = None) -> T:
        """Cache-first provider call that keeps Gaana traffic down:

        * a fresh copy is served for `ttl`;
        * a "not found" answer is remembered, so missing items aren't re-requested;
        * the last good copy is kept much longer and served while the provider is
          unavailable (blocked / rate-limited), so pages don't go blank during a block.
          `stale_key` lets several request shapes (e.g. list sizes) share that copy.
        """
        stale_key = f"stale:{stale_key or key}"
        hit = await self.cache.get(key)
        if hit is not None:
            try:
                return adapter.validate_python(hit)
            except ValueError:
                await self.cache.delete(key)
        if await self.cache.get(f"miss:{key}"):
            raise ProviderNotFound("Not found")
        try:
            value = await factory()
        except ProviderNotFound:
            await self.cache.set(f"miss:{key}", True, self.settings.not_found_cache_ttl_seconds)
            raise
        except ProviderUnavailable:
            stale = await self.cache.get(stale_key)
            if stale is not None:
                try:
                    log.info("provider unavailable: serving last good copy of %s", key)
                    return adapter.validate_python(stale)
                except ValueError:
                    pass
            raise
        dumped = adapter.dump_python(value, mode="json")
        await self.cache.set(key, dumped, ttl)
        await self.cache.set(stale_key, dumped, self.settings.stale_cache_ttl_seconds)
        return value

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
    async def search(self, query: str, limit: int = 10) -> SearchResults:
        q = sanitize_query(query)
        results = SearchResults(query=query)
        if not q:
            return results
        ttl = self.settings.search_cache_ttl_seconds
        sections: dict[str, Awaitable] = {
            "songs": self._cached(f"search:songs:{q.lower()}:{limit}", ttl, TypeAdapter(list[Track]),
                                  lambda: self.provider.search_songs(q, limit)),
            "albums": self._cached(f"search:albums:{q.lower()}:{limit}", ttl, TypeAdapter(list[AlbumSummary]),
                                   lambda: self.provider.search_albums(q, limit)),
            "artists": self._cached(f"search:artists:{q.lower()}:{limit}", ttl, TypeAdapter(list[ArtistSummary]),
                                    lambda: self.provider.search_artists(q, limit)),
            "playlists": self._search_playlists(q, limit),
        }
        outcomes = await asyncio.gather(*sections.values(), return_exceptions=True)
        for name, outcome in zip(sections.keys(), outcomes, strict=True):
            if isinstance(outcome, ProviderNotFound):
                continue  # no results is not an error
            if isinstance(outcome, BaseException):
                results.errors[name] = _error_message(outcome)
                continue
            setattr(results, name, outcome)
        return results

    async def _search_playlists(self, q: str, limit: int) -> list[PlaylistSummary]:
        # GaanaPy has no playlist search; match against the live chart playlists instead.
        words = q.lower().split()
        charts = await self.charts(100)
        return [p for p in charts if all(w in p.title.lower() for w in words)][:limit]

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

    async def artist_card(self, artist_id: str) -> ArtistDetail:
        """Name and picture only, for the home page. Reuses a full artist page when one
        is cached; otherwise one lookup (no similar-artists call), kept for a day."""
        for limit in (10, 5):
            hit = await self.cache.get(f"artist:{artist_id}:{limit}")
            if hit:
                try:
                    return ArtistDetail.model_validate(hit).model_copy(update={"top_tracks": []})
                except ValueError:
                    pass

        async def load() -> ArtistDetail:
            detail = await self.provider.get_artist(artist_id, 1)
            return detail.model_copy(update={"top_tracks": [], "similar_artists": []})

        return await self._cached(f"artist-card:{artist_id}", self.settings.metadata_cache_ttl_seconds,
                                  TypeAdapter(ArtistDetail), load)

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
        n = self._list_size(limit)
        lang = language.strip().lower()
        tracks = await self._cached(f"trending:{lang}:{n}", self._home_ttl(), TypeAdapter(list[Track]),
                                    lambda: self.provider.trending(language, n), stale_key=f"trending:{lang}")
        return tracks[: limit or n]

    async def new_releases(self, language: str, limit: int | None = None) -> NewReleases:
        n = self._list_size(limit)
        lang = language.strip().lower()
        new = await self._cached(f"new:{lang}:{n}", self._home_ttl(), TypeAdapter(NewReleases),
                                 lambda: self.provider.new_releases(language, n), stale_key=f"new:{lang}")
        k = limit or n
        return new.model_copy(update={"tracks": new.tracks[:k], "albums": new.albums[:k]})

    async def charts(self, limit: int = 20) -> list[PlaylistSummary]:
        return await self._cached(f"charts:{limit}", self._home_ttl(), TypeAdapter(list[PlaylistSummary]),
                                  lambda: self.provider.charts(limit))

    async def playlist(self, playlist_id: str) -> PlaylistDetail:
        async def load() -> PlaylistDetail:
            detail = await self.provider.get_playlist(playlist_id)
            try:  # borrow title/artwork from the chart listing when this playlist is a chart
                meta = next((p for p in await self.charts(100) if p.id == playlist_id), None)
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
        """GaanaPy derives some quality URLs by string substitution, so check they exist."""
        if not self.settings.verify_stream_quality or self._probe is None:
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
        return str(exc) or "Music provider error"
    log.exception("unexpected search failure", exc_info=exc)
    return "Unexpected error"
