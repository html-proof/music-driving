"""User-owned playlists. Mutations lock the playlist row so concurrent edits keep positions consistent."""

from __future__ import annotations

import asyncio
import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.errors import ProviderError, ProviderNotFound
from app.models import Playlist, PlaylistSong
from app.models.base import utcnow
from app.repositories import catalog as catalog_repo
from app.schemas.library import (
    AddSongsResult,
    PlaylistCreate,
    PlaylistUpdate,
    UserPlaylistDetail,
    UserPlaylistEntry,
    UserPlaylistSummary,
)
from app.schemas.music import Track
from app.services.catalog_service import CatalogService


class PlaylistService:
    def __init__(self, db: AsyncSession, catalog: CatalogService, user_id: uuid.UUID):
        self.db = db
        self.catalog = catalog
        self.user_id = user_id

    async def _owned(self, playlist_id: uuid.UUID, lock: bool = False) -> Playlist:
        stmt = select(Playlist).where(Playlist.id == playlist_id)
        if lock:
            stmt = stmt.with_for_update()
        playlist = await self.db.scalar(stmt)
        # Same 404 for "missing" and "someone else's private playlist": no information leak.
        if playlist is None or (playlist.owner_id != self.user_id and not (playlist.is_public and not lock)):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Playlist not found")
        if lock and playlist.owner_id != self.user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Playlist not found")
        return playlist

    async def list(self) -> list[UserPlaylistSummary]:
        playlists = (
            await self.db.scalars(
                select(Playlist).where(Playlist.owner_id == self.user_id).order_by(Playlist.updated_at.desc())
            )
        ).all()
        return [await self._summary(p) for p in playlists]

    async def create(self, data: PlaylistCreate) -> UserPlaylistDetail:
        playlist = Playlist(owner_id=self.user_id, name=data.name.strip(), description=data.description,
                            is_public=data.is_public)
        self.db.add(playlist)
        await self.db.commit()
        return await self.detail(playlist.id)

    async def update(self, playlist_id: uuid.UUID, data: PlaylistUpdate) -> UserPlaylistDetail:
        playlist = await self._owned(playlist_id, lock=True)
        if data.name is not None:
            playlist.name = data.name.strip()
        if data.description is not None:
            playlist.description = data.description
        if data.is_public is not None:
            playlist.is_public = data.is_public
        playlist.updated_at = utcnow()
        await self.db.commit()
        return await self.detail(playlist_id)

    async def delete(self, playlist_id: uuid.UUID) -> None:
        playlist = await self._owned(playlist_id, lock=True)
        await self.db.delete(playlist)
        await self.db.commit()

    async def detail(self, playlist_id: uuid.UUID) -> UserPlaylistDetail:
        playlist = await self._owned(playlist_id)
        entries = (
            await self.db.scalars(
                select(PlaylistSong).where(PlaylistSong.playlist_id == playlist.id).order_by(PlaylistSong.position)
            )
        ).all()
        summary = await self._summary(playlist, entries=entries)
        return UserPlaylistDetail(
            **summary.model_dump(),
            owner_id=playlist.owner_id,
            tracks=[
                UserPlaylistEntry(track=catalog_repo.song_to_track(e.song), position=e.position, added_at=e.added_at)
                for e in entries
            ],
        )

    async def add_songs(self, playlist_id: uuid.UUID, song_ids: list[str]) -> AddSongsResult:
        await self._owned(playlist_id)  # cheap ownership check before provider calls
        unique_ids = list(dict.fromkeys(song_ids))
        # Fetch metadata outside the row lock: provider calls can be slow.
        fetched = await asyncio.gather(*[self.catalog.song(s) for s in unique_ids], return_exceptions=True)
        failed: dict[str, str] = {}
        tracks: list[Track] = []
        for sid, result in zip(unique_ids, fetched, strict=True):
            if isinstance(result, ProviderNotFound):
                failed[sid] = "Song not found at provider"
            elif isinstance(result, ProviderError):
                failed[sid] = "Music provider unavailable"
            elif isinstance(result, BaseException):
                raise result
            else:
                tracks.append(result)

        playlist = await self._owned(playlist_id, lock=True)
        existing = set(
            (
                await self.db.scalars(
                    select(PlaylistSong.song_id).where(PlaylistSong.playlist_id == playlist.id)
                )
            ).all()
        )
        next_pos = (
            await self.db.scalar(
                select(func.coalesce(func.max(PlaylistSong.position), -1)).where(
                    PlaylistSong.playlist_id == playlist.id
                )
            )
        ) + 1
        added, already = [], []
        for track in tracks:
            song = await catalog_repo.upsert_song(self.db, self.catalog.provider.name, track)
            if song.id in existing:
                already.append(track.id)
                continue
            self.db.add(PlaylistSong(playlist_id=playlist.id, song_id=song.id, position=next_pos))
            existing.add(song.id)
            next_pos += 1
            added.append(track.id)
        if added:
            playlist.updated_at = utcnow()
        await self.db.commit()
        return AddSongsResult(added=added, already_present=already, failed=failed,
                              playlist=await self.detail(playlist_id))

    async def remove_song(self, playlist_id: uuid.UUID, song_id: str) -> UserPlaylistDetail:
        playlist = await self._owned(playlist_id, lock=True)
        entries = await self._entries(playlist.id)
        target = next((e for e in entries if e.song.provider_id == song_id), None)
        if target is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Song is not in this playlist")
        await self.db.delete(target)
        await self.db.flush()
        await self._renumber([e for e in entries if e is not target])
        playlist.updated_at = utcnow()
        await self.db.commit()
        return await self.detail(playlist_id)

    async def reorder(self, playlist_id: uuid.UUID, song_ids: list[str]) -> UserPlaylistDetail:
        playlist = await self._owned(playlist_id, lock=True)
        entries = await self._entries(playlist.id)
        by_key = {e.song.provider_id: e for e in entries}
        if sorted(song_ids) != sorted(by_key):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "song_ids must contain exactly the playlist's current songs")
        await self._renumber([by_key[s] for s in song_ids])
        playlist.updated_at = utcnow()
        await self.db.commit()
        return await self.detail(playlist_id)

    async def _entries(self, playlist_id: uuid.UUID) -> list[PlaylistSong]:
        return list(
            (
                await self.db.scalars(
                    select(PlaylistSong).where(PlaylistSong.playlist_id == playlist_id).order_by(PlaylistSong.position)
                )
            ).all()
        )

    async def _renumber(self, ordered: list[PlaylistSong]) -> None:
        # Two passes avoid transient duplicate positions if a unique index is ever added.
        for i, e in enumerate(ordered):
            e.position = -(i + 1)
        await self.db.flush()
        for i, e in enumerate(ordered):
            e.position = i
        await self.db.flush()

    async def _summary(self, p: Playlist, entries: list[PlaylistSong] | None = None) -> UserPlaylistSummary:
        if entries is None:
            entries = (
                await self.db.scalars(
                    select(PlaylistSong).where(PlaylistSong.playlist_id == p.id).order_by(PlaylistSong.position).limit(4)
                )
            ).all()
            count = await self.db.scalar(
                select(func.count()).select_from(PlaylistSong).where(PlaylistSong.playlist_id == p.id)
            )
        else:
            count = len(entries)
        art = [e.song.image_medium for e in entries[:4] if e.song.image_medium]
        return UserPlaylistSummary(
            id=p.id, name=p.name, description=p.description, is_public=p.is_public, track_count=count or 0,
            artwork=art, created_at=p.created_at, updated_at=p.updated_at,
        )
