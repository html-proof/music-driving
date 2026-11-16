import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import Timestamps, UUIDPk, utcnow
from app.models.catalog import Artist, Song


class Playlist(UUIDPk, Timestamps, Base):
    __tablename__ = "playlists"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    is_public: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    entries: Mapped[list["PlaylistSong"]] = relationship(
        back_populates="playlist",
        cascade="all, delete-orphan",
        order_by="PlaylistSong.position",
    )


class PlaylistSong(UUIDPk, Base):
    __tablename__ = "playlist_songs"
    __table_args__ = (
        UniqueConstraint("playlist_id", "song_id", name="uq_playlist_songs_song"),
        Index("ix_playlist_songs_playlist_position", "playlist_id", "position"),
    )

    playlist_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("playlists.id", ondelete="CASCADE"), nullable=False
    )
    song_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("songs.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    playlist: Mapped[Playlist] = relationship(back_populates="entries")
    song: Mapped[Song] = relationship(lazy="joined")


class LikedSong(Base):
    __tablename__ = "liked_songs"
    __table_args__ = (Index("ix_liked_songs_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    song_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    song: Mapped[Song] = relationship(lazy="joined")


class FollowedArtist(Base):
    __tablename__ = "followed_artists"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    artist_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("artists.id", ondelete="CASCADE"), primary_key=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    artist: Mapped[Artist] = relationship(lazy="joined")


class ListeningHistory(UUIDPk, Base):
    __tablename__ = "listening_history"
    __table_args__ = (Index("ix_listening_history_user_played", "user_id", "played_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    song_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("songs.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("playback_sessions.id", ondelete="SET NULL")
    )
    played_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    seconds_listened: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    completed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    context: Mapped[str | None] = mapped_column(String(100))  # e.g. "album:tyler-herro"

    song: Mapped[Song] = relationship(lazy="joined")


class PlaybackSession(UUIDPk, Timestamps, Base):
    __tablename__ = "playback_sessions"
    __table_args__ = (Index("ix_playback_sessions_user_updated", "user_id", "updated_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    device_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("devices.id", ondelete="SET NULL"))
    queue: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)  # provider song ids
    current_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    position_seconds: Mapped[float] = mapped_column(Float, default=0, nullable=False)
    shuffle: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    repeat_mode: Mapped[str] = mapped_column(String(10), default="off", nullable=False)  # off|all|one
    quality: Mapped[str] = mapped_column(String(20), default="high", nullable=False)
    context: Mapped[str | None] = mapped_column(String(100))


class SearchHistory(UUIDPk, Base):
    __tablename__ = "search_history"
    __table_args__ = (Index("ix_search_history_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    query: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
