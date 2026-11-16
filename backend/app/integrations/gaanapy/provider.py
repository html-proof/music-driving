from collections import OrderedDict
from typing import Any

from app.integrations.errors import ProviderNotFound
from app.integrations.gaanapy import normalize as n
from app.integrations.gaanapy.client import GaanaPyClient
from app.integrations.provider import ProviderTrack
from app.schemas.music import (
    AlbumDetail,
    AlbumSummary,
    ArtistDetail,
    ArtistSummary,
    NewReleases,
    PlaylistDetail,
    PlaylistSummary,
    Track,
    TrackPage,
)


class GaanaProvider:
    name = "gaana"

    def __init__(self, client: GaanaPyClient, remember: int = 3000):
        self.client = client
        # Every song row a list or search returned. Records from songDetail carry stream
        # URLs, so playing a listed song needs no second song lookup on Gaana. Lite rows
        # (search, most lists) carry none (their stream is resolved at play time) but
        # still answer metadata lookups (playlist adds, queues, lyrics) without one.
        self._seen: OrderedDict[str, dict] = OrderedDict()
        self._remember_max = remember

    async def health(self) -> bool:
        return await self.client.health()

    def known_track(self, song_id: str) -> ProviderTrack | None:
        raw = self._seen.get(song_id)
        return ProviderTrack(n.track(raw), n.stream_urls(raw)) if raw else None

    def _harvest(self, payload: Any) -> Any:
        """Remember every song record found anywhere in a GaanaPy payload. A row without
        stream URLs never replaces one that has them."""
        stack = [payload]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                seo = item.get("seokey")
                if isinstance(seo, str) and seo and _is_song_row(item):
                    known = self._seen.get(seo)
                    if n.stream_urls(item) or known is None or not n.stream_urls(known):
                        self._seen[seo] = item
                    self._seen.move_to_end(seo)
                stack.extend(v for v in item.values() if isinstance(v, (dict, list)))
            elif isinstance(item, list):
                stack.extend(item)
        while len(self._seen) > self._remember_max:
            self._seen.popitem(last=False)
        return payload

    # Search rows are "lite" (built by GaanaPy from Gaana's search list in one request):
    # no stream URLs, album or duration; the stream is resolved when the song is played.
    async def search_songs(self, query: str, limit: int, page: int = 1) -> list[Track]:
        rows = n.records(self._harvest(await self.client.search_songs(query, limit, page)))
        return [n.track(r) for r in rows][:limit]

    async def search_albums(self, query: str, limit: int, page: int = 1) -> list[AlbumSummary]:
        rows = n.records(self._harvest(await self.client.search_albums(query, limit, page)))
        return [n.album_summary(r) for r in rows][:limit]

    async def search_artists(self, query: str, limit: int, page: int = 1) -> list[ArtistSummary]:
        rows = n.records(self._harvest(await self.client.search_artists(query, limit, page)))
        return [n.artist_summary(r) for r in rows][:limit]

    async def get_song(self, song_id: str) -> ProviderTrack:
        rows = n.records(self._harvest(await self.client.song_info(song_id)))
        # songDetail can return several versions; prefer the exact seokey.
        row = next((r for r in rows if r["seokey"] == song_id), rows[0] if rows else None)
        if row is None:
            raise ProviderNotFound(f"Song {song_id} not found")
        return ProviderTrack(n.track(row), n.stream_urls(row))

    async def get_album(self, album_id: str) -> AlbumDetail:
        rows = n.records(self._harvest(await self.client.album_info(album_id)))
        if not rows:
            raise ProviderNotFound(f"Album {album_id} not found")
        return n.album_detail(rows[0])

    async def similar_albums(self, album_numeric_id: str, limit: int) -> list[AlbumSummary]:
        return [n.album_summary(r) for r in n.records(self._harvest(await self.client.similar_albums(album_numeric_id, limit)))]

    async def get_artist(self, artist_id: str, limit: int) -> ArtistDetail:
        rows = n.records(self._harvest(await self.client.artist_info(artist_id, limit)))
        if not rows:
            raise ProviderNotFound(f"Artist {artist_id} not found")
        return n.artist_detail(rows[0])

    async def artist_tracks(self, artist_numeric_id: str, limit: int, page: int) -> TrackPage:
        payload = self._harvest(await self.client.artist_tracks(artist_numeric_id, limit, page))
        items = [n.track(r) for r in n.records((payload or {}).get("tracks"))]
        total = payload.get("total") if isinstance(payload, dict) else None
        total = total if isinstance(total, int) else None
        # GaanaPy's `total` is the number returned in this page, so infer has_more from page fullness.
        return TrackPage(items=items, page=page, limit=limit, total=None, has_more=len(items) >= limit)

    async def similar_artists(self, artist_numeric_id: str, limit: int) -> list[ArtistSummary]:
        return [n.artist_summary(r) for r in n.records(self._harvest(await self.client.similar_artists(artist_numeric_id, limit)))]

    async def trending(self, language: str, limit: int) -> list[Track]:
        return [n.track(r) for r in n.records(self._harvest(await self.client.trending(language, limit)))]

    async def new_releases(self, language: str, limit: int) -> NewReleases:
        payload = self._harvest(await self.client.new_releases(language, limit)) or {}
        return NewReleases(
            language=language,
            tracks=[n.track(r) for r in n.records(payload.get("tracks"))],
            albums=[n.album_summary(r) for r in n.records(payload.get("albums"))],
        )

    async def charts(self, limit: int) -> list[PlaylistSummary]:
        return [n.playlist_summary(r) for r in n.records(self._harvest(await self.client.charts(limit)))]

    async def get_playlist(self, playlist_id: str) -> PlaylistDetail:
        tracks = [n.track(r) for r in n.records(self._harvest(await self.client.playlist_info(playlist_id)))]
        if not tracks:
            raise ProviderNotFound(f"Playlist {playlist_id} not found")
        # GaanaPy only returns the tracks; metadata is filled in by the catalog service.
        return PlaylistDetail(id=playlist_id, title=playlist_id.replace("-", " ").title(), tracks=tracks)


def _is_song_row(item: dict) -> bool:
    """Song rows (songDetail records and lite rows) carry `track_id` and `stream_urls`;
    album, artist and playlist rows do not."""
    return "track_id" in item and "stream_urls" in item
