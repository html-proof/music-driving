import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Query, Response, status

from app.dependencies import DB, Catalog, CurrentUser, Lyrics
from app.integrations.errors import ProviderNotFound
from app.schemas.library import CompleteIn, PlaybackSessionIn, PlaybackSessionOut, ProgressIn, QueueOut
from app.schemas.lyrics import Lyrics as LyricsOut
from app.schemas.music import AudioQuality, StreamInfo
from app.services.playback_service import PlaybackService

router = APIRouter(tags=["playback"])

SongId = Annotated[str, Path(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9\-]+$")]


@router.post("/playback/session", response_model=PlaybackSessionOut)
async def upsert_session(body: PlaybackSessionIn, user: CurrentUser, db: DB, catalog: Catalog) -> PlaybackSessionOut:
    """Create or replace this device's playback session (queue, position, shuffle/repeat)."""
    return await PlaybackService(db, catalog, user.id).upsert_session(body)


@router.get("/playback/stream/{song_id}", response_model=StreamInfo)
async def stream(song_id: SongId, user: CurrentUser, catalog: Catalog,
                 quality: AudioQuality | None = None) -> StreamInfo:
    """Resolve a fresh, verified HLS URL. The app streams directly from the provider CDN;
    the backend never proxies or stores audio. Call again before `expires_at`."""
    q = quality or AudioQuality(user.preferences.audio_quality if user.preferences else "high")
    try:
        return await catalog.stream(song_id, q)
    except ProviderNotFound as exc:
        # The provider's own wording ("Unable to find any results!") reads like a search
        # error in the player; say what it means for this song.
        raise ProviderNotFound("This song isn't available to stream") from exc


@router.post("/playback/progress", response_model=PlaybackSessionOut | None)
async def progress(body: ProgressIn, user: CurrentUser, db: DB, catalog: Catalog, response: Response):
    result = await PlaybackService(db, catalog, user.id).progress(body)
    if result is None:
        response.status_code = status.HTTP_204_NO_CONTENT
    return result


@router.post("/playback/complete")
async def complete(body: CompleteIn, user: CurrentUser, db: DB, catalog: Catalog) -> dict:
    recorded = await PlaybackService(db, catalog, user.id).complete(body)
    return {"recorded": recorded}


@router.get("/playback/queue", response_model=QueueOut)
async def queue(user: CurrentUser, db: DB, catalog: Catalog,
                session_id: Annotated[uuid.UUID | None, Query()] = None) -> QueueOut:
    return await PlaybackService(db, catalog, user.id).queue(session_id)


@router.get("/lyrics/{song_id}", response_model=LyricsOut, tags=["lyrics"])
async def lyrics(song_id: SongId, catalog: Catalog, lyrics_service: Lyrics) -> LyricsOut:
    # Lyrics are cached per song: answer from the cache without any catalogue lookup.
    cached = await lyrics_service.cached(song_id)
    if cached is not None:
        return cached
    track = await catalog.song(song_id)
    return await lyrics_service.for_track(track)
