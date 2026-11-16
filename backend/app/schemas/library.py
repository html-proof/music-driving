import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.music import ArtistSummary, AudioQuality, Track


class LikedSongOut(BaseModel):
    track: Track
    liked_at: datetime


class LikedPage(BaseModel):
    items: list[LikedSongOut]
    total: int
    offset: int
    limit: int


class LikeStatus(BaseModel):
    song_id: str
    liked: bool


class FollowedArtistOut(BaseModel):
    artist: ArtistSummary
    followed_at: datetime


class HistoryEntry(BaseModel):
    id: uuid.UUID
    track: Track
    played_at: datetime
    seconds_listened: float
    completed: bool
    context: str | None = None


class HistoryPage(BaseModel):
    items: list[HistoryEntry]
    offset: int
    limit: int
    has_more: bool


class SearchHistoryCreate(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class PlaylistCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    is_public: bool = False


class PlaylistUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    is_public: bool | None = None


class PlaylistAddSongs(BaseModel):
    song_ids: list[str] = Field(min_length=1, max_length=100, description="Provider song ids (seokeys)")


class PlaylistReorder(BaseModel):
    song_ids: list[str] = Field(description="Full list of the playlist's song ids in the new order")


class UserPlaylistSummary(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    is_public: bool
    track_count: int
    artwork: list[str] = Field(default=[], description="Up to 4 artwork URLs for a mosaic cover")
    created_at: datetime
    updated_at: datetime


class UserPlaylistEntry(BaseModel):
    track: Track
    position: int
    added_at: datetime


class UserPlaylistDetail(UserPlaylistSummary):
    owner_id: uuid.UUID
    tracks: list[UserPlaylistEntry]


class AddSongsResult(BaseModel):
    added: list[str]
    already_present: list[str]
    failed: dict[str, str]
    playlist: UserPlaylistDetail


# --- playback -------------------------------------------------------------
class PlaybackSessionIn(BaseModel):
    queue: list[str] = Field(default=[], max_length=500, description="Provider song ids")
    current_index: int = Field(0, ge=0)
    position_seconds: float = Field(0, ge=0)
    shuffle: bool = False
    repeat_mode: str = Field("off", pattern="^(off|all|one)$")
    quality: AudioQuality = AudioQuality.high
    context: str | None = Field(default=None, max_length=100)
    installation_id: str | None = None


class PlaybackSessionOut(BaseModel):
    id: uuid.UUID
    queue: list[str]
    current_index: int
    position_seconds: float
    shuffle: bool
    repeat_mode: str
    quality: AudioQuality
    context: str | None
    updated_at: datetime


class QueueOut(BaseModel):
    session_id: uuid.UUID | None
    current_index: int
    position_seconds: float
    shuffle: bool
    repeat_mode: str
    quality: AudioQuality | None
    tracks: list[Track]
    unavailable: list[str] = Field(default=[], description="Queue ids whose metadata could not be loaded")


class ProgressIn(BaseModel):
    session_id: uuid.UUID | None = None
    song_id: str
    position_seconds: float = Field(ge=0)
    current_index: int | None = Field(default=None, ge=0)


class CompleteIn(BaseModel):
    session_id: uuid.UUID | None = None
    song_id: str
    seconds_listened: float = Field(ge=0)
    completed: bool = Field(True, description="False when skipped before the end")
    context: str | None = Field(default=None, max_length=100)
