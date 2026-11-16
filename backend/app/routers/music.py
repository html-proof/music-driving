from typing import Annotated

from fastapi import APIRouter, Header, Path, Query

from app.dependencies import DB, Catalog, OptionalUser
from app.schemas.music import (
    AlbumDetail,
    AlbumSummary,
    ArtistDetail,
    HomeFeed,
    NewReleases,
    PlaylistDetail,
    PlaylistSummary,
    SearchResults,
    Track,
    TrackPage,
)
from app.services.home_service import HomeService
from app.services.library_service import LibraryService

router = APIRouter(tags=["music"])

Seokey = Annotated[str, Path(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9\-]+$")]
# Provider-side numeric id (Gaana: digits; Audius: short hash id).
NumericId = Annotated[str, Path(min_length=1, max_length=20, pattern=r"^[A-Za-z0-9]+$")]
Language = Annotated[str, Query(min_length=2, max_length=50, pattern=r"^[A-Za-z]+(?: [A-Za-z]+)*$")]


def _lang(language: str | None, user, catalog) -> str:
    if language:
        return language.strip().title()
    if user is not None and user.preferences and user.preferences.languages:
        return user.preferences.languages[0]
    return catalog.settings.default_language_list[0]


@router.get("/home", response_model=HomeFeed)
async def home(
    db: DB, catalog: Catalog, user: OptionalUser,
    languages: Annotated[str | None, Query(description="Comma separated, overrides user preferences")] = None,
    x_timezone: Annotated[str | None, Header(description="IANA timezone for the greeting")] = None,
) -> HomeFeed:
    langs = [lang.strip().title() for lang in languages.split(",") if lang.strip()] if languages else None
    return await HomeService(db, catalog).feed(user, langs, x_timezone)


@router.get("/search", response_model=SearchResults)
async def search(
    db: DB, catalog: Catalog, user: OptionalUser,
    q: Annotated[str, Query(min_length=1, max_length=200)],
    limit: Annotated[int, Query(ge=1, le=30)] = 10,
    save: Annotated[bool, Query(description="Store in the user's search history")] = False,
) -> SearchResults:
    results = await catalog.search(q, limit)
    if save and user is not None:
        await LibraryService(db, catalog, user.id).record_search(q)
    return results


@router.get("/songs/{seokey}", response_model=Track)
async def song(seokey: Seokey, catalog: Catalog) -> Track:
    return await catalog.song(seokey)


@router.get("/albums/{seokey}", response_model=AlbumDetail)
async def album(seokey: Seokey, catalog: Catalog) -> AlbumDetail:
    return await catalog.album(seokey)


@router.get("/albums/{album_id}/similar", response_model=list[AlbumSummary])
async def similar_albums(album_id: NumericId, catalog: Catalog,
                         limit: Annotated[int, Query(ge=1, le=30)] = 10) -> list[AlbumSummary]:
    return await catalog.similar_albums(album_id, limit)


@router.get("/artists/{seokey}", response_model=ArtistDetail)
async def artist(seokey: Seokey, db: DB, catalog: Catalog, user: OptionalUser,
                 limit: Annotated[int, Query(ge=1, le=50)] = 10) -> ArtistDetail:
    detail = await catalog.artist(seokey, limit)
    if user is not None:
        detail.is_followed = await LibraryService(db, catalog, user.id).is_following(seokey)
    return detail


@router.get("/artists/{artist_id}/tracks", response_model=TrackPage)
async def artist_tracks(artist_id: NumericId, catalog: Catalog,
                        limit: Annotated[int, Query(ge=1, le=50)] = 20,
                        page: Annotated[int, Query(ge=1, le=1000)] = 1) -> TrackPage:
    return await catalog.artist_tracks(artist_id, limit, page)


@router.get("/playlists/{seokey}", response_model=PlaylistDetail,
            summary="Provider (editorial/chart) playlist. Read user playlists via /library/playlists/{id}.")
async def provider_playlist(seokey: Seokey, catalog: Catalog) -> PlaylistDetail:
    return await catalog.playlist(seokey)


@router.get("/trending", response_model=list[Track])
async def trending(catalog: Catalog, user: OptionalUser, language: Language | None = None,
                   limit: Annotated[int | None, Query(ge=1, le=50, description="Defaults to the home row size")] = None,
                   ) -> list[Track]:
    return await catalog.trending(_lang(language, user, catalog), limit)


@router.get("/new-releases", response_model=NewReleases)
async def new_releases(catalog: Catalog, user: OptionalUser, language: Language | None = None,
                       limit: Annotated[int | None, Query(ge=1, le=50, description="Defaults to the home row size")] = None,
                       ) -> NewReleases:
    return await catalog.new_releases(_lang(language, user, catalog), limit)


@router.get("/charts", response_model=list[PlaylistSummary])
async def charts(catalog: Catalog, limit: Annotated[int, Query(ge=1, le=50)] = 20) -> list[PlaylistSummary]:
    return await catalog.charts(limit)
