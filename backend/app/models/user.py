import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import Timestamps, UUIDPk, utcnow


class User(UUIDPk, Timestamps, Base):
    """An anonymous, device-bound account. The app generates a random device id and a
    high-entropy secret on first launch; the secret's hash is the only credential."""

    __tablename__ = "users"

    device_id: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    secret_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Bumped on logout-everywhere / password change: invalidates outstanding access tokens.
    token_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    profile: Mapped["UserProfile"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )
    preferences: Mapped["UserPreferences"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )
    notification_preferences: Mapped["NotificationPreferences"] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan", lazy="selectin"
    )


class UserProfile(Timestamps, Base):
    __tablename__ = "user_profiles"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(1024))
    country: Mapped[str | None] = mapped_column(String(2))

    user: Mapped[User] = relationship(back_populates="profile")


class UserPreferences(Timestamps, Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    languages: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    audio_quality: Mapped[str] = mapped_column(String(20), default="high", nullable=False)
    allow_explicit: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship(back_populates="preferences")


class NotificationPreferences(Timestamps, Base):
    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    new_releases: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    recommendations: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    followed_artists: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user: Mapped[User] = relationship(back_populates="notification_preferences")


class RefreshToken(UUIDPk, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # All tokens produced by rotating one login share a family; reuse of a rotated
    # token revokes the whole family (refresh-token theft detection).
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Device(UUIDPk, Timestamps, Base):
    __tablename__ = "devices"
    __table_args__ = (UniqueConstraint("user_id", "installation_id", name="uq_devices_user_installation"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    installation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str | None] = mapped_column(String(100))
    push_token: Mapped[str | None] = mapped_column(String(512))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
