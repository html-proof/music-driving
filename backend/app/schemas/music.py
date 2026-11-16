from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class AudioQuality(StrEnum):
    low = "low"  # ~16 kbps AAC (HLS)
    medium = "medium"  # ~64 kbps
    high = "high"  # ~128 kbps
    very_high = "very_high"  # ~320 kbps


QUALITY_ORDER = [AudioQuality.very_high, AudioQuality.high, AudioQuality.medium, AudioQuality.low]
QUALITY_BITRATE_KBPS = {
    AudioQuality.low: 16,
    AudioQuality.medium: 64,
    AudioQuality.high: 128,
    AudioQuality.very_high: 320,
}


class Artwork(BaseModel):
    small: str | None = None
    medium: str | None = None
    large: str | None = None


class ArtistRef(BaseModel):
    name: str
    id: str | None = Field(default=None, description="Provider seokey, when known")
    numeric_id: str | None = None


class AlbumRef(BaseModel):
    id: str | None = None
    numeric_id: str | None = None
    title: str


class Track(BaseModel):
    id: str = Field(description="Provider song seokey; use it for every song_id path parameter")
    track_id: str | None = None
    title: str
    artists: list[ArtistRef] = []
    album: AlbumRef | None = None
    duration: int = Field(0, description="Seconds")
    language: str | None = None
    genres: list[str] = []
    is_explicit: bool = False
    release_date: str | None = None
    artwork: Artwork = Artwork()
    playable: bool = Field(False, description="Provider returned a stream for this track")
    provider_url: str | None = None


class AlbumSummary(BaseModel):
    id: str
    numeric_id: str | None = None
    title: str
    artists: list[ArtistRef] = []
    artwork: Artwork = Artwork()
    release_date: str | None = None
    language: str | None = None
    track_count: int | None = None
    is_explicit: bool = False


class AlbumDetail(AlbumSummary):
    label: str | None = None
    duration: int | None = None
    tracks: list[Track] = []


class ArtistSummary(BaseModel):
    id: str
    numeric_id: str | None = None
    name: str
    artwork: Artwork = Artwork()
    song_count: int | None = None
    album_count: int | None = None
    follower_count: int | None = None


class ArtistDetail(ArtistSummary):
    top_tracks: list[Track] = []
    total_tracks: int | None = None
    similar_artists: list[ArtistSummary] = []
    is_followed: bool = False


class PlaylistSummary(BaseModel):
    id: str
    numeric_id: str | None = None
    title: str
    language: str | None = None
    artwork: Artwork = Artwork()
    play_count: str | None = None
    is_explicit: bool = False


class PlaylistDetail(PlaylistSummary):
    tracks: list[Track] = []


class TrackPage(BaseModel):
    items: list[Track]
    page: int
    limit: int
    total: int | None = None
    has_more: bool


class SearchResults(BaseModel):
    query: str
    songs: list[Track] = []
    albums: list[AlbumSummary] = []
    artists: list[ArtistSummary] = []
    playlists: list[PlaylistSummary] = []
    errors: dict[str, str] = Field(
        default_factory=dict, description="Per-section provider failures (section -> message)"
    )


class HomeSection(BaseModel):
    id: str
    title: str
    subtitle: str | None = None
    type: str = Field(description="tracks | albums | artists | playlists")
    tracks: list[Track] = []
    albums: list[AlbumSummary] = []
    artists: list[ArtistSummary] = []
    playlists: list[PlaylistSummary] = []


class HomeFeed(BaseModel):
    greeting: str
    languages: list[str]
    sections: list[HomeSection]
    errors: dict[str, str] = {}
    # Languages whose songs could not be loaded right now (provider busy / blocking, and
    # no earlier copy to fall back on); the app tells the user instead of hiding them.
    unavailable_languages: list[str] = []


class NewReleases(BaseModel):
    language: str
    tracks: list[Track] = []
    albums: list[AlbumSummary] = []


class StreamInfo(BaseModel):
    song_id: str
    quality: AudioQuality
    requested_quality: AudioQuality
    url: str
    format: str = "hls"
    bitrate_kbps: int
    expires_at: datetime | None = Field(None, description="Refresh the URL (call this endpoint again) before this")
    available_qualities: list[AudioQuality]


class Recommendation(BaseModel):
    track: Track
    reason: str


class Recommendations(BaseModel):
    personalized: bool
    message: str | None = None
    items: list[Recommendation] = []
    based_on: dict[str, list[str]] = {}
