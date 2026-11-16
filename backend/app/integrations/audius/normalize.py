"""Convert Audius JSON into the app's provider-independent schemas."""

from typing import Any

from hashids import Hashids

from app.schemas.music import (
    AlbumDetail,
    AlbumRef,
    AlbumSummary,
    ArtistDetail,
    ArtistRef,
    ArtistSummary,
    Artwork,
    PlaylistDetail,
    PlaylistSummary,
    Track,
)

# Audius addresses everything by Hashids of its numeric ids (public scheme used by its
# own SDKs); album backlinks only carry the numeric id.
_HASHIDS = Hashids(salt="azowernasdfoia", min_length=5)


def encode_id(numeric: Any) -> str | None:
    try:
        return _HASHIDS.encode(int(numeric)) or None
    except (TypeError, ValueError):
        return None


def _s(value: Any) -> str | None:
    value = str(value).strip() if value is not None else ""
    return value or None


def _date(value: Any) -> str | None:
    v = _s(value)
    return v[:10] if v else None


def artwork(images: dict | None) -> Artwork:
    images = images or {}
    small, medium, large = _s(images.get("150x150")), _s(images.get("480x480")), _s(images.get("1000x1000"))
    return Artwork(small=small or medium or large, medium=medium or large or small, large=large or medium or small)


def is_playable(raw: dict) -> bool:
    """Only tracks the artist offers as a free full stream."""
    access = raw.get("access") or {}
    return bool(raw.get("is_streamable")) and not raw.get("is_stream_gated") and access.get("stream", True) \
        and not raw.get("is_delete") and raw.get("is_available", True)


def artist_ref(user: dict | None) -> list[ArtistRef]:
    if not user or not user.get("id"):
        return []
    return [ArtistRef(name=_s(user.get("name")) or user.get("handle") or "Unknown artist", id=user["id"],
                      numeric_id=user["id"])]


def track(raw: dict) -> Track:
    album = raw.get("album_backlink") or None
    return Track(
        id=raw["id"],
        track_id=_s(raw.get("track_id")),
        title=(_s(raw.get("title")) or "Untitled"),
        artists=artist_ref(raw.get("user")),
        album=AlbumRef(id=encode_id(album.get("playlist_id")), numeric_id=encode_id(album.get("playlist_id")),
                       title=_s(album.get("playlist_name")) or "Album") if isinstance(album, dict) else None,
        duration=int(raw.get("duration") or 0),
        genres=[g for g in [_s(raw.get("genre"))] if g],
        is_explicit=bool(raw.get("parental_warning_type")),
        release_date=_date(raw.get("release_date") or raw.get("created_at")),
        artwork=artwork(raw.get("artwork")),
        playable=is_playable(raw),
        provider_url=f"https://audius.co{raw['permalink']}" if raw.get("permalink") else None,
    )


def artist_summary(user: dict) -> ArtistSummary:
    return ArtistSummary(
        id=user["id"],
        numeric_id=user["id"],
        name=_s(user.get("name")) or user.get("handle") or "Unknown artist",
        artwork=artwork(user.get("profile_picture")),
        song_count=user.get("track_count"),
        album_count=user.get("album_count"),
        follower_count=user.get("follower_count"),
    )


def artist_detail(user: dict, top: list[dict]) -> ArtistDetail:
    return ArtistDetail(**artist_summary(user).model_dump(), top_tracks=[track(t) for t in top],
                        total_tracks=user.get("track_count"))


def album_summary(raw: dict) -> AlbumSummary:
    return AlbumSummary(
        id=raw["id"],
        numeric_id=raw["id"],
        title=_s(raw.get("playlist_name")) or "Untitled album",
        artists=artist_ref(raw.get("user")),
        artwork=artwork(raw.get("artwork")),
        release_date=_date(raw.get("release_date")),
        track_count=raw.get("track_count"),
    )


def album_detail(raw: dict, tracks: list[dict]) -> AlbumDetail:
    items = [track(t) for t in tracks]
    return AlbumDetail(**album_summary(raw).model_dump(), tracks=items,
                       duration=sum(t.duration for t in items) or None)


def playlist_summary(raw: dict) -> PlaylistSummary:
    plays = raw.get("total_play_count")
    return PlaylistSummary(
        id=raw["id"],
        numeric_id=raw["id"],
        title=_s(raw.get("playlist_name")) or "Untitled playlist",
        artwork=artwork(raw.get("artwork")),
        play_count=f"{plays:,}" if isinstance(plays, int) else None,
    )


def playlist_detail(raw: dict, tracks: list[dict]) -> PlaylistDetail:
    return PlaylistDetail(**playlist_summary(raw).model_dump(), tracks=[track(t) for t in tracks])
