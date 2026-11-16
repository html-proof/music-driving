"""Convert GaanaPy JSON into the app's provider-independent schemas."""

import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.schemas.music import (
    AlbumDetail,
    AlbumRef,
    AlbumSummary,
    ArtistDetail,
    ArtistRef,
    ArtistSummary,
    Artwork,
    AudioQuality,
    PlaylistSummary,
    Track,
)

_QUALITY_KEYS = {
    AudioQuality.very_high: "very_high_quality",
    AudioQuality.high: "high_quality",
    AudioQuality.medium: "medium_quality",
    AudioQuality.low: "low_quality",
}


def _s(value: Any) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _split(value: Any) -> list[str]:
    if not value:
        return []
    return [p.strip() for p in str(value).split(",") if p.strip()]


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def artwork(raw: dict) -> Artwork:
    urls = ((raw or {}).get("images") or {}).get("urls") or {}
    small, medium, large = _s(urls.get("small_artwork")), _s(urls.get("medium_artwork")), _s(urls.get("large_artwork"))
    # Fill gaps from the nearest available size rather than leaving holes.
    return Artwork(small=small or medium or large, medium=medium or large or small, large=large or medium or small)


def artist_refs(names: Any, seokeys: Any, ids: Any) -> list[ArtistRef]:
    names_l, keys_l, ids_l = _split(names), _split(seokeys), _split(ids)
    if names_l and len(names_l) == len(keys_l):
        return [
            ArtistRef(name=n, id=k, numeric_id=ids_l[i] if len(ids_l) == len(names_l) else None)
            for i, (n, k) in enumerate(zip(names_l, keys_l, strict=True))
        ]
    # Counts disagree (common on album records): only link names whose slug matches a known key.
    key_set = set(keys_l)
    key_to_id = dict(zip(keys_l, ids_l, strict=False)) if len(keys_l) == len(ids_l) else {}
    refs = []
    for n in names_l:
        slug = slugify(n)
        key = slug if slug in key_set else None
        refs.append(ArtistRef(name=n, id=key, numeric_id=key_to_id.get(key) if key else None))
    return refs


def stream_urls(raw: dict) -> dict[AudioQuality, str]:
    urls = ((raw or {}).get("stream_urls") or {}).get("urls") or {}
    return {q: u for q, key in _QUALITY_KEYS.items() if (u := _s(urls.get(key)))}


def stream_expiry(url: str) -> datetime | None:
    """Akamai tokens look like `hdnts=st=...~exp=1794831381~acl=...`."""
    try:
        token = parse_qs(urlparse(url).query).get("hdnts", [""])[0]
        match = re.search(r"exp=(\d+)", token)
        return datetime.fromtimestamp(int(match.group(1)), UTC) if match else None
    except (ValueError, AttributeError):
        return None


def track(raw: dict) -> Track:
    album_title = _s(raw.get("album"))
    return Track(
        id=raw["seokey"],
        track_id=_s(raw.get("track_id")),
        title=_s(raw.get("title")) or raw["seokey"],
        artists=artist_refs(raw.get("artists"), raw.get("artist_seokeys"), raw.get("artist_ids")),
        album=AlbumRef(id=_s(raw.get("album_seokey")), numeric_id=_s(raw.get("album_id")), title=album_title)
        if album_title
        else None,
        duration=_int(raw.get("duration")) or 0,
        language=_s(raw.get("language")),
        genres=_split(raw.get("genres")),
        is_explicit=bool(raw.get("is_explicit")),
        release_date=_s(raw.get("release_date")),
        artwork=artwork(raw),
        playable=bool(stream_urls(raw)),
        provider_url=_s(raw.get("song_url")),
    )


def album_summary(raw: dict) -> AlbumSummary:
    return AlbumSummary(
        id=raw["seokey"],
        numeric_id=_s(raw.get("album_id")),
        title=_s(raw.get("title")) or raw["seokey"],
        artists=artist_refs(raw.get("artists"), raw.get("artist_seokeys"), raw.get("artist_ids")),
        artwork=artwork(raw),
        release_date=_s(raw.get("release_date")),
        language=_s(raw.get("language")),
        track_count=_int(raw.get("track_count")),
        is_explicit=bool(raw.get("is_explicit")),
    )


def album_detail(raw: dict) -> AlbumDetail:
    summary = album_summary(raw)
    tracks = [track(t) for t in raw.get("tracks") or [] if isinstance(t, dict) and t.get("seokey")]
    return AlbumDetail(
        **summary.model_dump(),
        label=_s(raw.get("label")),
        duration=_int(raw.get("duration")),
        tracks=tracks,
    )


def artist_summary(raw: dict) -> ArtistSummary:
    return ArtistSummary(
        id=raw["seokey"],
        numeric_id=_s(raw.get("artist_id")),
        name=_s(raw.get("name")) or raw["seokey"],
        artwork=artwork(raw),
        song_count=_int(raw.get("song_count")),
        album_count=_int(raw.get("album_count")),
        follower_count=_int(raw.get("favorite_count")),
    )


def artist_detail(raw: dict) -> ArtistDetail:
    top = [track(t) for t in raw.get("top_tracks") or [] if isinstance(t, dict) and t.get("seokey")]
    return ArtistDetail(**artist_summary(raw).model_dump(), top_tracks=top, total_tracks=_int(raw.get("total_tracks")))


def playlist_summary(raw: dict) -> PlaylistSummary:
    return PlaylistSummary(
        id=raw["seokey"],
        numeric_id=_s(raw.get("playlist_id")),
        title=_s(raw.get("title")) or raw["seokey"],
        language=_s(raw.get("language")),
        artwork=artwork(raw),
        play_count=_s(raw.get("play_count")),
        is_explicit=bool(raw.get("is_explicit")),
    )


def records(payload: Any) -> list[dict]:
    """GaanaPy returns lists, or {'error': ...} objects for empty sections."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict) and r.get("seokey")]
    return []
