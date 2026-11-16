import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, status

from app.dependencies import DB, Catalog, CurrentUser
from app.schemas.library import (
    AddSongsResult,
    FollowedArtistOut,
    HistoryPage,
    LikedPage,
    LikeStatus,
    PlaylistAddSongs,
    PlaylistCreate,
    PlaylistReorder,
    PlaylistUpdate,
    SearchHistoryCreate,
    UserPlaylistDetail,
    UserPlaylistSummary,
)
from app.schemas.music import Recommendations, Track
from app.services.library_service import LibraryService
from app.services.playlist_service import PlaylistService
from app.services.recommendation_service import RecommendationService

router = APIRouter(tags=["library"])

SongId = Annotated[str, Path(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9\-]+$")]


# --- liked songs -----------------------------------------------------------------
@router.post("/library/liked/{song_id}", response_model=LikeStatus)
async def like(song_id: SongId, user: CurrentUser, db: DB, catalog: Catalog) -> LikeStatus:
    await LibraryService(db, catalog, user.id).like(song_id)
    return LikeStatus(song_id=song_id, liked=True)


@router.delete("/library/liked/{song_id}", response_model=LikeStatus)
async def unlike(song_id: SongId, user: CurrentUser, db: DB, catalog: Catalog) -> LikeStatus:
    await LibraryService(db, catalog, user.id).unlike(song_id)
    return LikeStatus(song_id=song_id, liked=False)


@router.get("/library/liked", response_model=LikedPage)
async def liked(user: CurrentUser, db: DB, catalog: Catalog,
                offset: Annotated[int, Query(ge=0)] = 0,
                limit: Annotated[int, Query(ge=1, le=200)] = 50) -> LikedPage:
    return await LibraryService(db, catalog, user.id).liked(offset, limit)


@router.get("/library/liked/status", response_model=dict[str, bool])
async def liked_status(user: CurrentUser, db: DB, catalog: Catalog,
                       ids: Annotated[str, Query(description="Comma separated song ids", max_length=5000)]
                       ) -> dict[str, bool]:
    song_ids = [i.strip() for i in ids.split(",") if i.strip()][:200]
    return await LibraryService(db, catalog, user.id).liked_status(song_ids)


# --- followed artists --------------------------------------------------------------
@router.get("/library/followed-artists", response_model=list[FollowedArtistOut])
async def followed(user: CurrentUser, db: DB, catalog: Catalog) -> list[FollowedArtistOut]:
    return await LibraryService(db, catalog, user.id).followed()


@router.post("/library/followed-artists/{artist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def follow(artist_id: SongId, user: CurrentUser, db: DB, catalog: Catalog) -> None:
    await LibraryService(db, catalog, user.id).follow(artist_id)


@router.delete("/library/followed-artists/{artist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unfollow(artist_id: SongId, user: CurrentUser, db: DB, catalog: Catalog) -> None:
    await LibraryService(db, catalog, user.id).unfollow(artist_id)


# --- history ---------------------------------------------------------------------
@router.get("/library/recently-played", response_model=list[Track])
async def recently_played(user: CurrentUser, db: DB, catalog: Catalog,
                          limit: Annotated[int, Query(ge=1, le=50)] = 20) -> list[Track]:
    return await LibraryService(db, catalog, user.id).recently_played(limit)


@router.get("/library/history", response_model=HistoryPage)
async def history(user: CurrentUser, db: DB, catalog: Catalog,
                  offset: Annotated[int, Query(ge=0)] = 0,
                  limit: Annotated[int, Query(ge=1, le=200)] = 50) -> HistoryPage:
    return await LibraryService(db, catalog, user.id).history(offset, limit)


@router.delete("/library/history", status_code=status.HTTP_204_NO_CONTENT)
async def clear_history(user: CurrentUser, db: DB, catalog: Catalog) -> None:
    await LibraryService(db, catalog, user.id).clear_history()


@router.get("/library/search-history")
async def search_history(user: CurrentUser, db: DB, catalog: Catalog,
                         limit: Annotated[int, Query(ge=1, le=50)] = 20) -> list[dict]:
    return await LibraryService(db, catalog, user.id).search_history(limit)


@router.post("/library/search-history", status_code=status.HTTP_204_NO_CONTENT,
             summary="Record a search (e.g. when a result is tapped) without running it again")
async def record_search(body: SearchHistoryCreate, user: CurrentUser, db: DB, catalog: Catalog) -> None:
    await LibraryService(db, catalog, user.id).record_search(body.query)


@router.delete("/library/search-history", status_code=status.HTTP_204_NO_CONTENT)
async def clear_search_history(user: CurrentUser, db: DB, catalog: Catalog,
                               entry_id: uuid.UUID | None = None) -> None:
    await LibraryService(db, catalog, user.id).delete_search(entry_id)


@router.get("/recommendations", response_model=Recommendations)
async def recommendations(user: CurrentUser, db: DB, catalog: Catalog,
                          limit: Annotated[int, Query(ge=1, le=50)] = 30) -> Recommendations:
    return await RecommendationService(db, catalog, user.id).recommend(limit)


# --- user playlists ----------------------------------------------------------------
@router.get("/library/playlists", response_model=list[UserPlaylistSummary])
async def my_playlists(user: CurrentUser, db: DB, catalog: Catalog) -> list[UserPlaylistSummary]:
    return await PlaylistService(db, catalog, user.id).list()


@router.get("/library/playlists/{playlist_id}", response_model=UserPlaylistDetail)
async def my_playlist(playlist_id: uuid.UUID, user: CurrentUser, db: DB, catalog: Catalog) -> UserPlaylistDetail:
    return await PlaylistService(db, catalog, user.id).detail(playlist_id)


@router.post("/playlists", response_model=UserPlaylistDetail, status_code=status.HTTP_201_CREATED)
async def create_playlist(body: PlaylistCreate, user: CurrentUser, db: DB, catalog: Catalog) -> UserPlaylistDetail:
    return await PlaylistService(db, catalog, user.id).create(body)


@router.put("/playlists/{playlist_id}", response_model=UserPlaylistDetail)
async def update_playlist(playlist_id: uuid.UUID, body: PlaylistUpdate, user: CurrentUser, db: DB,
                          catalog: Catalog) -> UserPlaylistDetail:
    return await PlaylistService(db, catalog, user.id).update(playlist_id, body)


@router.delete("/playlists/{playlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_playlist(playlist_id: uuid.UUID, user: CurrentUser, db: DB, catalog: Catalog) -> None:
    await PlaylistService(db, catalog, user.id).delete(playlist_id)


@router.post("/playlists/{playlist_id}/songs", response_model=AddSongsResult)
async def add_songs(playlist_id: uuid.UUID, body: PlaylistAddSongs, user: CurrentUser, db: DB,
                    catalog: Catalog) -> AddSongsResult:
    return await PlaylistService(db, catalog, user.id).add_songs(playlist_id, body.song_ids)


@router.delete("/playlists/{playlist_id}/songs/{song_id}", response_model=UserPlaylistDetail)
async def remove_song(playlist_id: uuid.UUID, song_id: SongId, user: CurrentUser, db: DB,
                      catalog: Catalog) -> UserPlaylistDetail:
    return await PlaylistService(db, catalog, user.id).remove_song(playlist_id, song_id)


@router.put("/playlists/{playlist_id}/order", response_model=UserPlaylistDetail)
async def reorder(playlist_id: uuid.UUID, body: PlaylistReorder, user: CurrentUser, db: DB,
                  catalog: Catalog) -> UserPlaylistDetail:
    return await PlaylistService(db, catalog, user.id).reorder(playlist_id, body.song_ids)
