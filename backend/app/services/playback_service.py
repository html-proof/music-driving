"""Playback sessions (cross-device queue state) and listening history."""

import asyncio
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.errors import ProviderError
from app.models import Device, ListeningHistory, PlaybackSession
from app.repositories import catalog as catalog_repo
from app.schemas.library import CompleteIn, PlaybackSessionIn, PlaybackSessionOut, ProgressIn, QueueOut
from app.schemas.music import AudioQuality
from app.services.catalog_service import CatalogService
from app.services.library_service import ensure_song

# A play shorter than this is not written to history (avoids noise from rapid skipping).
MIN_SECONDS_FOR_HISTORY = 5.0


def _out(s: PlaybackSession) -> PlaybackSessionOut:
    return PlaybackSessionOut(
        id=s.id, queue=s.queue, current_index=s.current_index, position_seconds=s.position_seconds,
        shuffle=s.shuffle, repeat_mode=s.repeat_mode, quality=AudioQuality(s.quality), context=s.context,
        updated_at=s.updated_at,
    )


class PlaybackService:
    def __init__(self, db: AsyncSession, catalog: CatalogService, user_id: uuid.UUID):
        self.db = db
        self.catalog = catalog
        self.user_id = user_id

    async def _session(self, session_id: uuid.UUID | None) -> PlaybackSession | None:
        if session_id is None:
            return await self.latest()
        s = await self.db.get(PlaybackSession, session_id)
        if s is None or s.user_id != self.user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Playback session not found")
        return s

    async def latest(self) -> PlaybackSession | None:
        return await self.db.scalar(
            select(PlaybackSession)
            .where(PlaybackSession.user_id == self.user_id)
            .order_by(PlaybackSession.updated_at.desc())
            .limit(1)
        )

    async def upsert_session(self, data: PlaybackSessionIn) -> PlaybackSessionOut:
        if data.queue and data.current_index >= len(data.queue):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "current_index is outside the queue")
        device_id = None
        if data.installation_id:
            device_id = await self.db.scalar(
                select(Device.id).where(Device.user_id == self.user_id, Device.installation_id == data.installation_id)
            )
        # One session per device (or one device-less session) per user.
        session = await self.db.scalar(
            select(PlaybackSession).where(
                PlaybackSession.user_id == self.user_id,
                PlaybackSession.device_id.is_(None) if device_id is None else PlaybackSession.device_id == device_id,
            )
        )
        if session is None:
            session = PlaybackSession(user_id=self.user_id, device_id=device_id)
            self.db.add(session)
        session.queue = list(data.queue)
        session.current_index = data.current_index
        session.position_seconds = data.position_seconds
        session.shuffle = data.shuffle
        session.repeat_mode = data.repeat_mode
        session.quality = data.quality.value
        session.context = data.context
        await self.db.commit()
        await self.db.refresh(session)
        return _out(session)

    async def progress(self, data: ProgressIn) -> PlaybackSessionOut | None:
        session = await self._session(data.session_id)
        if session is None:
            return None
        session.position_seconds = data.position_seconds
        if data.current_index is not None and data.current_index < len(session.queue):
            session.current_index = data.current_index
        elif data.song_id in session.queue:
            session.current_index = session.queue.index(data.song_id)
        await self.db.commit()
        await self.db.refresh(session)
        return _out(session)

    async def complete(self, data: CompleteIn) -> bool:
        """Record a finished (or skipped) play in listening history. Returns whether it was stored."""
        if data.seconds_listened < MIN_SECONDS_FOR_HISTORY:
            return False
        session = await self._session(data.session_id) if data.session_id else None
        song = await ensure_song(self.db, self.catalog, data.song_id)
        self.db.add(
            ListeningHistory(
                user_id=self.user_id,
                song_id=song.id,
                session_id=session.id if session else None,
                seconds_listened=data.seconds_listened,
                completed=data.completed,
                context=data.context or (session.context if session else None),
            )
        )
        await self.db.commit()
        return True

    async def queue(self, session_id: uuid.UUID | None) -> QueueOut:
        session = await self._session(session_id)
        if session is None:
            return QueueOut(session_id=None, current_index=0, position_seconds=0, shuffle=False, repeat_mode="off",
                            quality=None, tracks=[])
        # Prefer the local catalogue copy; fall back to the provider for unknown ids.
        tracks, unavailable = [], []
        missing: list[str] = []
        local = {}
        for sid in session.queue:
            song = await catalog_repo.get_song(self.db, self.catalog.provider.name, sid)
            if song is not None:
                local[sid] = catalog_repo.song_to_track(song)
            else:
                missing.append(sid)
        fetched = await asyncio.gather(*[self.catalog.song(s) for s in missing], return_exceptions=True)
        for sid, result in zip(missing, fetched, strict=True):
            if isinstance(result, ProviderError):
                unavailable.append(sid)
            elif isinstance(result, BaseException):
                raise result
            else:
                local[sid] = result
        tracks = [local[s] for s in session.queue if s in local]
        # Unavailable songs are dropped, so shift the index to the same song in `tracks`.
        current = sum(1 for s in session.queue[: session.current_index] if s in local)
        current = min(current, max(len(tracks) - 1, 0))
        return QueueOut(
            session_id=session.id, current_index=current, position_seconds=session.position_seconds,
            shuffle=session.shuffle, repeat_mode=session.repeat_mode, quality=AudioQuality(session.quality),
            tracks=tracks, unavailable=unavailable,
        )
