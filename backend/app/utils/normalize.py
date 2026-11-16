"""Convert raw GaanaPy dictionaries into the app's normalised models.

GaanaPy returns strings for most numbers, comma-joined artist lists and empty strings
for missing values; everything here tolerates missing or malformed fields.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from app.schemas import (
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

QUALITY_KEYS = {
    "very_high": "very_high_quality",
    "high": "high_quality",
    "medium": "medium_quality",
    "low": "low_quality",
}
BITRATE_KBPS = {"very_high": 320, "high": 128, "medium": 64, "low": 16}


def text(value: Any) -> Optional[str]:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def number(value: Any) -> Optional[int]:
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def split(value: Any) -> List[str]:
    if not value:
        return []
    return [p.strip() for p in str(value).split(",") if p.strip()]


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def records(payload: Any) -> List[Dict]:
    """GaanaPy returns lists, or {'error': ...} objects when a section is empty."""
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict) and r.get("seokey") and "error" not in r]
    return []


def artwork(raw: Dict) -> Artwork:
    urls = ((raw or {}).get("images") or {}).get("urls") or {}
    small = text(urls.get("small_artwork"))
    medium = text(urls.get("medium_artwork"))
    large = text(urls.get("large_artwork"))
    # Fill gaps from the nearest available size instead of leaving holes.
    return Artwork(small=small or medium or large, medium=medium or large or small, large=large or medium or small)


def artist_refs(names: Any, seokeys: Any, ids: Any) -> List[ArtistRef]:
    names_l, keys_l, ids_l = split(names), split(seokeys), split(ids)
    if names_l and len(names_l) == len(keys_l):
        return [
            ArtistRef(name=n, id=k, numeric_id=ids_l[i] if len(ids_l) == len(names_l) else None)
            for i, (n, k) in enumerate(zip(names_l, keys_l))
        ]
    # Counts disagree (common for albums): only link names whose slug matches a known key.
    key_to_id = dict(zip(keys_l, ids_l)) if len(keys_l) == len(ids_l) else {}
    refs = []
    for n in names_l:
        slug = slugify(n)
        key = slug if slug in keys_l else None
        refs.append(ArtistRef(name=n, id=key, numeric_id=key_to_id.get(key) if key else None))
    return refs


def stream_urls(raw: Dict) -> Dict[str, str]:
    urls = ((raw or {}).get("stream_urls") or {}).get("urls") or {}
    out = {}
    for quality, key in QUALITY_KEYS.items():
        url = text(urls.get(key))
        if url and url.startswith("https://"):
            out[quality] = url
    return out


def stream_expiry(url: str) -> Optional[datetime]:
    """Akamai tokens look like `hdnts=st=...~exp=1794831381~acl=...`."""
    try:
        token = parse_qs(urlparse(url).query).get("hdnts", [""])[0]
        match = re.search(r"exp=(\d+)", token)
        return datetime.fromtimestamp(int(match.group(1)), timezone.utc) if match else None
    except (ValueError, AttributeError, OverflowError):
        return None


def track(raw: Dict) -> Track:
    album_title = text(raw.get("album"))
    return Track(
        id=raw["seokey"],
        track_id=text(raw.get("track_id")),
        title=text(raw.get("title")) or raw["seokey"],
        artists=artist_refs(raw.get("artists"), raw.get("artist_seokeys"), raw.get("artist_ids")),
        album=AlbumRef(id=text(raw.get("album_seokey")), numeric_id=text(raw.get("album_id")), title=album_title)
        if album_title
        else None,
        duration=number(raw.get("duration")) or 0,
        language=text(raw.get("language")),
        genres=split(raw.get("genres")),
        is_explicit=bool(raw.get("is_explicit")),
        release_date=text(raw.get("release_date")),
        play_count=text(raw.get("play_count")),
        artwork=artwork(raw),
        playable=bool(stream_urls(raw)),
    )


def tracks(payload: Any) -> List[Track]:
    return [track(r) for r in records(payload)]


def album_summary(raw: Dict) -> AlbumSummary:
    return AlbumSummary(
        id=raw["seokey"],
        numeric_id=text(raw.get("album_id")),
        title=text(raw.get("title")) or raw["seokey"],
        artists=artist_refs(raw.get("artists"), raw.get("artist_seokeys"), raw.get("artist_ids")),
        artwork=artwork(raw),
        release_date=text(raw.get("release_date")),
        language=text(raw.get("language")),
        track_count=number(raw.get("track_count")),
        is_explicit=bool(raw.get("is_explicit")),
    )


def album_detail(raw: Dict) -> AlbumDetail:
    return AlbumDetail(
        **album_summary(raw).model_dump(),
        label=text(raw.get("label")),
        duration=number(raw.get("duration")),
        tracks=tracks(raw.get("tracks")),
    )


def artist_summary(raw: Dict) -> ArtistSummary:
    return ArtistSummary(
        id=raw["seokey"],
        numeric_id=text(raw.get("artist_id")),
        name=text(raw.get("name")) or raw["seokey"],
        artwork=artwork(raw),
        song_count=number(raw.get("song_count")),
        album_count=number(raw.get("album_count")),
        follower_count=number(raw.get("favorite_count")),
    )


def albums_from_tracks(items: List[Track], limit: int = 12) -> List[AlbumSummary]:
    """Distinct albums referenced by a list of tracks (track artwork is the album cover)."""
    seen, out = set(), []
    for t in items:
        if not t.album or not t.album.id or t.album.id in seen:
            continue
        seen.add(t.album.id)
        out.append(AlbumSummary(
            id=t.album.id, numeric_id=t.album.numeric_id, title=t.album.title,
            artists=t.artists, artwork=t.artwork, release_date=t.release_date, language=t.language,
            is_explicit=t.is_explicit,
        ))
        if len(out) >= limit:
            break
    return out


def artists_from_tracks(raw_tracks: List[Dict], limit: int = 12) -> List[ArtistSummary]:
    """Distinct lead artists of a list of raw tracks, using the artist photo Gaana attaches to each song."""
    seen, out = set(), []
    for raw in raw_tracks:
        refs = artist_refs(raw.get("artists"), raw.get("artist_seokeys"), raw.get("artist_ids"))
        image = text(raw.get("artist_image"))
        if not refs or not refs[0].id or not image or refs[0].id in seen:
            continue
        lead = refs[0]
        seen.add(lead.id)
        out.append(ArtistSummary(
            id=lead.id, numeric_id=lead.numeric_id, name=lead.name,
            artwork=Artwork(small=image, medium=image, large=image),
        ))
        if len(out) >= limit:
            break
    return out


def artist_detail(raw: Dict, similar: List[ArtistSummary]) -> ArtistDetail:
    top = tracks(raw.get("top_tracks"))
    return ArtistDetail(
        **artist_summary(raw).model_dump(),
        top_tracks=top,
        total_tracks=number(raw.get("total_tracks")),
        albums=albums_from_tracks(top),
        similar_artists=similar,
    )


def playlist_summary(raw: Dict) -> PlaylistSummary:
    return PlaylistSummary(
        id=raw["seokey"],
        numeric_id=text(raw.get("playlist_id")),
        title=text(raw.get("title")) or raw["seokey"],
        language=text(raw.get("language")),
        artwork=artwork(raw),
        play_count=text(raw.get("play_count")),
        is_explicit=bool(raw.get("is_explicit")),
    )


def title_from_seokey(seokey: str) -> str:
    return " ".join(w.upper() if len(w) <= 2 and w.isalpha() else w.capitalize() for w in seokey.split("-"))


def playlist_detail(seokey: str, raw_tracks: Any, meta: Optional[PlaylistSummary]) -> PlaylistDetail:
    items = tracks(raw_tracks)
    if meta is None:
        cover = items[0].artwork if items else Artwork()
        meta = PlaylistSummary(id=seokey, title=title_from_seokey(seokey), artwork=cover)
    return PlaylistDetail(**meta.model_dump(), tracks=items)
