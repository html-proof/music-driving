"""User library: likes, followed artists, history, search history. All queries are scoped by user."""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import FollowedArtist, LikedSong, ListeningHistory, SearchHistory, Song
from app.repositories import catalog as catalog_repo
from app.schemas.library import (
    FollowedArtistOut,
    HistoryEntry,
    HistoryPage,
    LikedPage,
    LikedSongOut,
)
from app.schemas.music import ArtistSummary, Track
from app.services.catalog_service import CatalogService, sanitize_query


async def ensure_song(db: AsyncSession, catalog: CatalogService, song_id: str) -> Song:
    """Make sure the song exists locally, refreshing metadata from the provider."""
    track = await catalog.song(song_id)  # raises ProviderNotFound -> 404
    return await catalog_repo.upsert_song(db, catalog.provider.name, track)


class LibraryService:
    def __init__(self, db: AsyncSession, catalog: CatalogService, user_id: uuid.UUID):
        self.db = db
        self.catalog = catalog
        self.user_id = user_id

    @property
    def _provider(self) -> str:
        return self.catalog.provider.name

    # --- likes ---------------------------------------------------------------
    async def like(self, song_id: str) -> None:
        song = await ensure_song(self.db, self.catalog, song_id)
        exists = await self.db.get(LikedSong, (self.user_id, song.id))
        if exists is None:
            self.db.add(LikedSong(user_id=self.user_id, song_id=song.id))
        await self.db.commit()

    async def unlike(self, song_id: str) -> None:
        song = await catalog_repo.get_song(self.db, self.catalog.provider.name, song_id)
        if song is not None:
            await self.db.execute(
                delete(LikedSong).where(LikedSong.user_id == self.user_id, LikedSong.song_id == song.id)
            )
            await self.db.commit()

    async def liked(self, offset: int, limit: int) -> LikedPage:
        total = await self.db.scalar(select(func.count()).select_from(LikedSong).where(LikedSong.user_id == self.user_id))
        rows = (
            await self.db.scalars(
                select(LikedSong)
                .where(LikedSong.user_id == self.user_id)
                .order_by(LikedSong.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
        return LikedPage(
            items=[LikedSongOut(track=catalog_repo.song_to_track(r.song, self._provider), liked_at=r.created_at)
                   for r in rows],
            total=total or 0,
            offset=offset,
            limit=limit,
        )

    async def liked_status(self, song_ids: list[str]) -> dict[str, bool]:
        if not song_ids:
            return {}
        rows = await self.db.execute(
            select(Song.provider_id)
            .join(LikedSong, LikedSong.song_id == Song.id)
            .where(LikedSong.user_id == self.user_id, Song.provider_id.in_(song_ids))
        )
        liked = {r[0] for r in rows}
        return {sid: sid in liked for sid in song_ids}

    # --- followed artists ----------------------------------------------------
    async def follow(self, artist_id: str) -> None:
        detail = await self.catalog.artist(artist_id)
        artist = await catalog_repo.upsert_artist(self.db, self.catalog.provider.name, detail)
        if await self.db.get(FollowedArtist, (self.user_id, artist.id)) is None:
            self.db.add(FollowedArtist(user_id=self.user_id, artist_id=artist.id))
        await self.db.commit()

    async def unfollow(self, artist_id: str) -> None:
        artist = await catalog_repo.get_artist(self.db, self.catalog.provider.name, artist_id)
        if artist is not None:
            await self.db.execute(
                delete(FollowedArtist).where(
                    FollowedArtist.user_id == self.user_id, FollowedArtist.artist_id == artist.id
                )
            )
            await self.db.commit()

    async def is_following(self, artist_id: str) -> bool:
        artist = await catalog_repo.get_artist(self.db, self.catalog.provider.name, artist_id)
        if artist is None:
            return False
        return await self.db.get(FollowedArtist, (self.user_id, artist.id)) is not None

    async def followed(self) -> list[FollowedArtistOut]:
        rows = (
            await self.db.scalars(
                select(FollowedArtist)
                .where(FollowedArtist.user_id == self.user_id)
                .order_by(FollowedArtist.created_at.desc())
            )
        ).all()
        return [FollowedArtistOut(artist=catalog_repo.artist_to_summary(r.artist), followed_at=r.created_at) for r in rows]

    async def followed_summaries(self) -> list[ArtistSummary]:
        return [f.artist for f in await self.followed()]

    # --- history -------------------------------------------------------------
    async def history(self, offset: int, limit: int) -> HistoryPage:
        rows = (
            await self.db.scalars(
                select(ListeningHistory)
                .where(ListeningHistory.user_id == self.user_id)
                .order_by(ListeningHistory.played_at.desc())
                .offset(offset)
                .limit(limit + 1)
            )
        ).all()
        items = [
            HistoryEntry(
                id=r.id,
                track=catalog_repo.song_to_track(r.song, self._provider),
                played_at=r.played_at,
                seconds_listened=r.seconds_listened,
                completed=r.completed,
                context=r.context,
            )
            for r in rows[:limit]
        ]
        return HistoryPage(items=items, offset=offset, limit=limit, has_more=len(rows) > limit)

    async def recently_played(self, limit: int = 20) -> list[Track]:
        """Distinct songs of the active provider, most recent play first (songs played
        with another provider can't be streamed now, so they are left out)."""
        last_play = func.max(ListeningHistory.played_at).label("last_play")
        sub = (
            select(ListeningHistory.song_id, last_play)
            .where(ListeningHistory.user_id == self.user_id)
            .group_by(ListeningHistory.song_id)
            .subquery()
        )
        rows = (
            await self.db.execute(
                select(Song)
                .join(sub, sub.c.song_id == Song.id)
                .where(Song.provider == self._provider)
                .order_by(sub.c.last_play.desc())
                .limit(limit)
            )
        ).scalars().all()
        return [catalog_repo.song_to_track(s, self._provider) for s in rows]

    async def clear_history(self) -> None:
        await self.db.execute(delete(ListeningHistory).where(ListeningHistory.user_id == self.user_id))
        await self.db.commit()

    # --- search history ------------------------------------------------------
    async def record_search(self, query: str) -> None:
        query = sanitize_query(query)
        if not query:
            return
        await self.db.execute(
            delete(SearchHistory).where(
                SearchHistory.user_id == self.user_id, func.lower(SearchHistory.query) == query.lower()
            )
        )
        self.db.add(SearchHistory(user_id=self.user_id, query=query))
        await self.db.commit()

    async def search_history(self, limit: int = 20) -> list[dict]:
        rows = (
            await self.db.scalars(
                select(SearchHistory)
                .where(SearchHistory.user_id == self.user_id)
                .order_by(SearchHistory.created_at.desc())
                .limit(limit)
            )
        ).all()
        return [{"id": str(r.id), "query": r.query, "created_at": r.created_at} for r in rows]

    async def delete_search(self, entry_id: uuid.UUID | None) -> None:
        stmt = delete(SearchHistory).where(SearchHistory.user_id == self.user_id)
        if entry_id is not None:
            stmt = stmt.where(SearchHistory.id == entry_id)
        await self.db.execute(stmt)
        await self.db.commit()


def not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, f"{what} not found")
