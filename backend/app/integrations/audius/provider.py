import asyncio
from collections import OrderedDict
from typing import ClassVar

from app.integrations.audius import normalize as n
from app.integrations.audius.client import AudiusClient
from app.integrations.errors import ProviderNotFound
from app.integrations.provider import ProviderTrack
from app.schemas.music import (
    AlbumDetail,
    AlbumSummary,
    ArtistDetail,
    ArtistSummary,
    AudioQuality,
    NewReleases,
    PlaylistDetail,
    PlaylistSummary,
    Track,
    TrackPage,
)

# Audius genre names, as accepted by /tracks/trending?genre=.
GENRES = [
    "Electronic", "Hip-Hop/Rap", "Pop", "R&B/Soul", "Lo-Fi", "House", "Rock", "Alternative", "Ambient",
    "Dubstep", "Drum & Bass", "Techno", "Trap", "Jazz", "Acoustic", "Classical", "Latin", "Reggae",
    "Country", "Folk", "Metal", "Soundtrack", "World", "Experimental",
]
_GENRE_KEYS = {"".join(ch for ch in g.lower() if ch.isalnum()): g for g in GENRES}
ALL = "All"


def genre_for(category: str | None) -> str | None:
    """The Audius genre matching a language/category name, or None for "every genre".
    Audius has no languages, so the app's language preferences only narrow the feed when
    they happen to name a genre ("Pop", "Jazz", "Hiphop Rap", ...)."""
    if not category:
        return None
    return _GENRE_KEYS.get("".join(ch for ch in category.lower() if ch.isalnum()))


class AudiusProvider:
    name = "audius"
    # Trending/new are filtered by genre, not language (see `categories_for`).
    uses_languages = False
    # One progressive MP3 per track behind a redirecting endpoint: nothing to verify.
    stream_format = "mp3"
    verify_streams = False
    section_titles: ClassVar[dict[str, str]] = {
        "new_albums": "Top albums", "new_tracks": "Fresh & underground", "charts": "Trending playlists",
    }

    def __init__(self, client: AudiusClient, remember: int = 3000):
        self.client = client
        # Lists already carry full track records; remembering them lets a listed song
        # play without a second /tracks/{id} lookup.
        self._seen: OrderedDict[str, Track] = OrderedDict()
        self._remember_max = remember

    async def health(self) -> bool:
        return await self.client.health()

    def categories_for(self, languages: list[str]) -> list[str]:
        """Genres named in the user's language list, else one all-genre feed."""
        genres = list(dict.fromkeys(g for g in (genre_for(lang) for lang in languages) if g))
        return genres or [ALL]

    def _stream(self, t: Track) -> dict[AudioQuality, str]:
        return {AudioQuality.high: self.client.stream_url(t.id)} if t.playable else {}

    def known_track(self, song_id: str) -> ProviderTrack | None:
        t = self._seen.get(song_id)
        return ProviderTrack(t, self._stream(t)) if t else None

    def _tracks(self, rows: list[dict]) -> list[Track]:
        tracks = [n.track(r) for r in rows if isinstance(r, dict) and r.get("id")]
        for t in tracks:
            self._seen[t.id] = t
            self._seen.move_to_end(t.id)
        while len(self._seen) > self._remember_max:
            self._seen.popitem(last=False)
        return tracks

    # --- search -------------------------------------------------------------------
    async def search_songs(self, query: str, limit: int) -> list[Track]:
        return self._tracks(await self.client.search_tracks(query, limit))

    async def search_albums(self, query: str, limit: int) -> list[AlbumSummary]:
        # Albums are playlists flagged is_album; over-fetch, then filter.
        rows = await self.client.search_playlists(query, min(limit * 3, 100))
        return [n.album_summary(r) for r in rows if r.get("is_album")][:limit]

    async def search_artists(self, query: str, limit: int) -> list[ArtistSummary]:
        return [n.artist_summary(u) for u in await self.client.search_users(query, limit)]

    async def search_playlists(self, query: str, limit: int) -> list[PlaylistSummary]:
        rows = await self.client.search_playlists(query, min(limit * 2, 100))
        return [n.playlist_summary(r) for r in rows if not r.get("is_album")][:limit]

    # --- items --------------------------------------------------------------------
    async def get_song(self, song_id: str) -> ProviderTrack:
        raw = await self.client.track(song_id)
        if not raw:
            raise ProviderNotFound(f"Song {song_id} not found")
        t = self._tracks([raw])[0]
        return ProviderTrack(t, self._stream(t))

    async def get_album(self, album_id: str) -> AlbumDetail:
        raw, tracks = await asyncio.gather(self.client.playlist(album_id), self.client.playlist_tracks(album_id))
        self._tracks(tracks)
        return n.album_detail(raw, tracks)

    async def similar_albums(self, album_numeric_id: str, limit: int) -> list[AlbumSummary]:
        # No similarity endpoint: other albums by the same artist.
        raw = await self.client.playlist(album_numeric_id)
        owner = (raw.get("user") or {}).get("id")
        if not owner:
            return []
        rows = await self.client.user_albums(owner, limit + 1)
        return [n.album_summary(r) for r in rows if r.get("id") != album_numeric_id][:limit]

    async def get_artist(self, artist_id: str, limit: int) -> ArtistDetail:
        user, top = await asyncio.gather(self.client.user(artist_id),
                                         self.client.user_tracks(artist_id, limit, sort="plays"))
        if not user:
            raise ProviderNotFound(f"Artist {artist_id} not found")
        self._tracks(top)
        return n.artist_detail(user, top)

    async def artist_tracks(self, artist_numeric_id: str, limit: int, page: int) -> TrackPage:
        rows = await self.client.user_tracks(artist_numeric_id, limit, offset=(page - 1) * limit)
        return TrackPage(items=self._tracks(rows), page=page, limit=limit, total=None,
                         has_more=len(rows) >= limit)

    async def similar_artists(self, artist_numeric_id: str, limit: int) -> list[ArtistSummary]:
        return [n.artist_summary(u) for u in await self.client.related_users(artist_numeric_id, limit)]

    async def get_playlist(self, playlist_id: str) -> PlaylistDetail:
        raw, tracks = await asyncio.gather(self.client.playlist(playlist_id),
                                           self.client.playlist_tracks(playlist_id))
        self._tracks(tracks)
        return n.playlist_detail(raw, tracks)

    # --- discovery ----------------------------------------------------------------
    async def trending(self, language: str, limit: int) -> list[Track]:
        """Trending this week, in the genre `language` names (all genres otherwise)."""
        return self._tracks(await self.client.trending(limit, genre=genre_for(language)))

    async def new_releases(self, language: str, limit: int) -> NewReleases:
        # Audius has no "new releases" feed: underground trending (newer, smaller artists)
        # and the top albums stand in, titled as such on Home (`section_titles`).
        tracks, albums = await asyncio.gather(self.client.trending_underground(limit),
                                              self.client.top_albums(min(limit, 20)))
        return NewReleases(language=language, tracks=self._tracks(tracks),
                           albums=[n.album_summary(r) for r in albums])

    async def charts(self, limit: int) -> list[PlaylistSummary]:
        return [n.playlist_summary(r) for r in await self.client.trending_playlists(limit)]
