"""Local copies of provider catalogue entities.

These rows exist so user data (likes, playlists, history) can reference songs with
foreign keys and render offline. The provider stays the source of truth: rows are
refreshed whenever the provider returns fresher metadata, and stream URLs are never
stored here.
"""

from sqlalchemy import Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import Timestamps, UUIDPk


class Artist(UUIDPk, Timestamps, Base):
    __tablename__ = "artists"
    __table_args__ = (UniqueConstraint("provider", "provider_id", name="uq_artists_provider_id"),)

    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="gaana")
    provider_id: Mapped[str] = mapped_column(String(255), nullable=False)  # seokey
    provider_numeric_id: Mapped[str | None] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(1024))


class Album(UUIDPk, Timestamps, Base):
    __tablename__ = "albums"
    __table_args__ = (UniqueConstraint("provider", "provider_id", name="uq_albums_provider_id"),)

    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="gaana")
    provider_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_numeric_id: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    artists: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    image_url: Mapped[str | None] = mapped_column(String(1024))
    release_date: Mapped[str | None] = mapped_column(String(20))
    language: Mapped[str | None] = mapped_column(String(50))


class Song(UUIDPk, Timestamps, Base):
    __tablename__ = "songs"
    __table_args__ = (UniqueConstraint("provider", "provider_id", name="uq_songs_provider_id"),)

    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="gaana")
    provider_id: Mapped[str] = mapped_column(String(255), nullable=False)  # seokey
    provider_track_id: Mapped[str | None] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    artists: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    artist_seokeys: Mapped[str] = mapped_column(String(1000), default="", nullable=False)
    artist_ids: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    album: Mapped[str | None] = mapped_column(String(500))
    album_seokey: Mapped[str | None] = mapped_column(String(255))
    album_id: Mapped[str | None] = mapped_column(String(32))
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    language: Mapped[str | None] = mapped_column(String(50), index=True)
    genres: Mapped[str | None] = mapped_column(String(500))
    is_explicit: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    image_small: Mapped[str | None] = mapped_column(String(1024))
    image_medium: Mapped[str | None] = mapped_column(String(1024))
    image_large: Mapped[str | None] = mapped_column(String(1024))
    release_date: Mapped[str | None] = mapped_column(String(20))
