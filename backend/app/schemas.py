"""Normalised response models shared by every endpoint (and mirrored by the Flutter models)."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field


class Artwork(BaseModel):
    small: Optional[str] = None
    medium: Optional[str] = None
    large: Optional[str] = None


class ArtistRef(BaseModel):
    name: str
    id: Optional[str] = Field(None, description="Artist seokey, when known")
    numeric_id: Optional[str] = None


class AlbumRef(BaseModel):
    title: str
    id: Optional[str] = Field(None, description="Album seokey")
    numeric_id: Optional[str] = None


class Track(BaseModel):
    id: str = Field(description="Song seokey; use it for /songs/{id} and /songs/{id}/stream")
    track_id: Optional[str] = None
    title: str
    artists: List[ArtistRef] = []
    album: Optional[AlbumRef] = None
    duration: int = Field(0, description="Seconds")
    language: Optional[str] = None
    genres: List[str] = []
    is_explicit: bool = False
    release_date: Optional[str] = None
    play_count: Optional[str] = None
    artwork: Artwork = Artwork()
    playable: bool = Field(False, description="The provider returned an audio stream for this song")


class AlbumSummary(BaseModel):
    id: str
    numeric_id: Optional[str] = None
    title: str
    artists: List[ArtistRef] = []
    artwork: Artwork = Artwork()
    release_date: Optional[str] = None
    language: Optional[str] = None
    track_count: Optional[int] = None
    is_explicit: bool = False


class AlbumDetail(AlbumSummary):
    label: Optional[str] = None
    duration: Optional[int] = None
    tracks: List[Track] = []


class ArtistSummary(BaseModel):
    id: str
    numeric_id: Optional[str] = None
    name: str
    artwork: Artwork = Artwork()
    song_count: Optional[int] = None
    album_count: Optional[int] = None
    follower_count: Optional[int] = None


class ArtistDetail(ArtistSummary):
    top_tracks: List[Track] = []
    total_tracks: Optional[int] = None
    albums: List[AlbumSummary] = Field([], description="Albums that this artist's popular songs come from")
    similar_artists: List[ArtistSummary] = []


class PlaylistSummary(BaseModel):
    id: str
    numeric_id: Optional[str] = None
    title: str
    language: Optional[str] = None
    artwork: Artwork = Artwork()
    play_count: Optional[str] = None
    is_explicit: bool = False


class PlaylistDetail(PlaylistSummary):
    tracks: List[Track] = []


class TrackPage(BaseModel):
    items: List[Track]
    page: int
    limit: int
    has_more: bool


class NewReleases(BaseModel):
    language: str
    tracks: List[Track] = []
    albums: List[AlbumSummary] = []


class HomeSection(BaseModel):
    id: str
    title: str
    subtitle: Optional[str] = None
    type: str = Field(description="tracks | albums | artists | playlists")
    tracks: List[Track] = []
    albums: List[AlbumSummary] = []
    artists: List[ArtistSummary] = []
    playlists: List[PlaylistSummary] = []


class HomeFeed(BaseModel):
    language: str
    languages: List[str]
    sections: List[HomeSection]
    errors: dict = Field({}, description="Sections that failed to load, with the reason")


class SearchResults(BaseModel):
    query: str
    songs: List[Track] = []
    albums: List[AlbumSummary] = []
    artists: List[ArtistSummary] = []
    playlists: List[PlaylistSummary] = []
    errors: dict = {}


class StreamInfo(BaseModel):
    song_id: str
    url: str = Field(description="HLS (.m3u8) master playlist, AAC audio only")
    format: str = "hls"
    codec: str = "aac"
    quality: str
    requested_quality: str
    bitrate_kbps: int
    expires_at: Optional[str] = Field(None, description="ISO-8601 UTC; request a new URL before this")
    available_qualities: List[str] = []


class LyricLine(BaseModel):
    time_ms: int
    text: str


class Lyrics(BaseModel):
    song_id: str
    available: bool
    synced: bool
    instrumental: bool = False
    lines: List[LyricLine] = []
    plain_text: Optional[str] = None
    source: str = "lrclib"
