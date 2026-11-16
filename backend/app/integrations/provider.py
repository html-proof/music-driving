"""Provider adapter interface.

The rest of the backend talks only to `MusicProvider`. Swapping GaanaPy for another
catalogue means writing a new implementation of this protocol; the Flutter app and the
routers stay unchanged.
"""

from typing import Protocol

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


class ProviderTrack:
    """A track plus its short-lived stream URLs (never sent to clients as-is)."""

    def __init__(self, track: Track, streams: dict[AudioQuality, str]):
        self.track = track
        self.streams = streams


class MusicProvider(Protocol):
    name: str

    async def health(self) -> bool: ...
    async def search_songs(self, query: str, limit: int) -> list[Track]: ...
    async def search_albums(self, query: str, limit: int) -> list[AlbumSummary]: ...
    async def search_artists(self, query: str, limit: int) -> list[ArtistSummary]: ...
    async def get_song(self, song_id: str) -> ProviderTrack: ...
    async def get_album(self, album_id: str) -> AlbumDetail: ...
    async def similar_albums(self, album_numeric_id: str, limit: int) -> list[AlbumSummary]: ...
    async def get_artist(self, artist_id: str, limit: int) -> ArtistDetail: ...
    async def artist_tracks(self, artist_numeric_id: str, limit: int, page: int) -> TrackPage: ...
    async def similar_artists(self, artist_numeric_id: str, limit: int) -> list[ArtistSummary]: ...
    async def trending(self, language: str, limit: int) -> list[Track]: ...
    async def new_releases(self, language: str, limit: int) -> NewReleases: ...
    async def charts(self, limit: int) -> list[PlaylistSummary]: ...
    async def get_playlist(self, playlist_id: str) -> PlaylistDetail: ...
