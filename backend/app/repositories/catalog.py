"""Upserts of provider entities into the local catalogue tables."""

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Artist, Song
from app.schemas.music import AlbumRef, ArtistRef, ArtistSummary, Artwork, Track


async def get_song(db: AsyncSession, provider: str, provider_id: str) -> Song | None:
    return await db.scalar(select(Song).where(Song.provider == provider, Song.provider_id == provider_id))


async def upsert_song(db: AsyncSession, provider: str, track: Track) -> Song:
    song = await get_song(db, provider, track.id)
    if song is None:
        song = Song(provider=provider, provider_id=track.id)
        _apply_track(song, track)
        try:
            async with db.begin_nested():
                db.add(song)
        except IntegrityError:  # created concurrently by another request
            song = await get_song(db, provider, track.id)
            assert song is not None
    _apply_track(song, track)
    await db.flush()
    return song


def _apply_track(song: Song, t: Track) -> None:
    song.provider_track_id = t.track_id
    song.title = t.title[:500]
    song.artists = ", ".join(a.name for a in t.artists)[:1000]
    song.artist_seokeys = ", ".join(a.id or "" for a in t.artists)[:1000]
    song.artist_ids = ", ".join(a.numeric_id or "" for a in t.artists)[:500]
    song.album = t.album.title if t.album else None
    song.album_seokey = t.album.id if t.album else None
    song.album_id = t.album.numeric_id if t.album else None
    song.duration_seconds = t.duration
    song.language = t.language
    song.genres = ", ".join(t.genres)[:500] or None
    song.is_explicit = t.is_explicit
    song.image_small, song.image_medium, song.image_large = t.artwork.small, t.artwork.medium, t.artwork.large
    song.release_date = t.release_date


def song_to_track(song: Song) -> Track:
    """Render a stored song (metadata only; playability is checked at stream time)."""
    names = [n.strip() for n in song.artists.split(",")] if song.artists else []
    keys = [k.strip() for k in song.artist_seokeys.split(",")] if song.artist_seokeys else []
    ids = [i.strip() for i in song.artist_ids.split(",")] if song.artist_ids else []
    artists = [
        ArtistRef(
            name=name,
            id=(keys[i] or None) if i < len(keys) else None,
            numeric_id=(ids[i] or None) if i < len(ids) else None,
        )
        for i, name in enumerate(names)
        if name
    ]
    return Track(
        id=song.provider_id,
        track_id=song.provider_track_id,
        title=song.title,
        artists=artists,
        album=AlbumRef(id=song.album_seokey, numeric_id=song.album_id, title=song.album) if song.album else None,
        duration=song.duration_seconds,
        language=song.language,
        genres=[g.strip() for g in (song.genres or "").split(",") if g.strip()],
        is_explicit=song.is_explicit,
        release_date=song.release_date,
        artwork=Artwork(small=song.image_small, medium=song.image_medium, large=song.image_large),
        playable=True,
    )


async def get_artist(db: AsyncSession, provider: str, provider_id: str) -> Artist | None:
    return await db.scalar(select(Artist).where(Artist.provider == provider, Artist.provider_id == provider_id))


async def upsert_artist(db: AsyncSession, provider: str, a: ArtistSummary) -> Artist:
    artist = await get_artist(db, provider, a.id)
    if artist is None:
        artist = Artist(provider=provider, provider_id=a.id, name=a.name)
        try:
            async with db.begin_nested():
                db.add(artist)
        except IntegrityError:
            artist = await get_artist(db, provider, a.id)
            assert artist is not None
    artist.name = a.name
    artist.provider_numeric_id = a.numeric_id
    artist.image_url = a.artwork.medium or a.artwork.large or a.artwork.small
    await db.flush()
    return artist


def artist_to_summary(artist: Artist) -> ArtistSummary:
    img = artist.image_url
    return ArtistSummary(
        id=artist.provider_id,
        numeric_id=artist.provider_numeric_id,
        name=artist.name,
        artwork=Artwork(small=img, medium=img, large=img),
    )
