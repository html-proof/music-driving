"""Local fix: build rows straight from Gaana list/search payloads.

Search results and lists (trending, new releases, playlists, albums, artist tracks)
already carry what a row needs (seokey, id, title, artwork, artists, language). Building
rows from them costs one Gaana request per list instead of one per row, which is what got
clients blocked. Rows use the same keys as the full formatters (format_json_songs /
format_json_albums / format_json_artists) with unknown fields left empty, plus
"lite": True. Stream links, when the payload has none, are resolved at play time through
/songs/info/.

Three payload shapes are understood:
  * search hits (`gr[].gd[]`): seo, id, ti, aw, sti / alist, language / lang
  * songDetail-like tracks: seokey, track_id, track_title, artwork*, artist[], album_title...
  * apiv2 entities: seokey, entity_id, name, artwork / atw / artwork_medium, and an
    `entity_info` list of {key, value} (artist, album, duration, stream_url...)
"""

import re

_SIZE = re.compile(r"size_[sml](?=[_.])")


def artwork_urls(url) -> dict:
    """small/medium/large variants of a Gaana artwork URL.

    Handles both `size_m.jpg` and timestamped `size_m_1712905431.jpg`; a URL without a
    size token is used for every size.
    """
    url = url if isinstance(url, str) else ""
    if not url:
        return {"large_artwork": "", "medium_artwork": "", "small_artwork": ""}
    return {
        "large_artwork": _SIZE.sub("size_l", url),
        "medium_artwork": _SIZE.sub("size_m", url),
        "small_artwork": _SIZE.sub("size_s", url),
    }


def entity_values(entity: dict) -> dict:
    """`entity_info: [{key, value}, ...]` as a dict (empty when absent)."""
    info = entity.get("entity_info") if isinstance(entity, dict) else None
    if not isinstance(info, list):
        return {}
    return {
        item.get("key"): item.get("value")
        for item in info
        if isinstance(item, dict) and item.get("key")
    }


def _first(sources: tuple, *keys):
    """First non-empty value for any of `keys`, looked up in each source in turn."""
    for key in keys:
        for source in sources:
            value = source.get(key)
            if value not in (None, "", [], {}):
                return value
    return ""


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ", ".join(_text(v) for v in value if _text(v))
    return str(value).strip()


def _names_from_string(value) -> str:
    """'Mithoon,Arijit Singh' or '[Mithoon,Arijit Singh]' -> 'Mithoon, Arijit Singh'."""
    if not isinstance(value, str):
        return ""
    value = value.strip().strip("[]")
    return ", ".join(part.strip() for part in value.split(",") if part.strip())


def _artist_fields(sources: tuple) -> tuple[str, str, str]:
    """(names, seokeys, ids), each comma+space joined, from the richest data available.

    Seokeys and ids are only given when every artist has them, so they always pair up
    with the names by position.
    """
    artists = _first(sources, "artist", "artists")
    if isinstance(artists, list) and artists and all(isinstance(a, dict) for a in artists):
        names = [_text(a.get("name")) for a in artists]
        seokeys = [_text(a.get("seokey")) for a in artists]
        ids = [_text(a.get("artist_id") or a.get("id")) for a in artists]
        if all(names):
            return (
                ", ".join(names),
                ", ".join(seokeys) if all(seokeys) else "",
                ", ".join(ids) if all(ids) else "",
            )
    if isinstance(artists, str) and artists:
        return _names_from_string(artists), "", ""
    return _names_from_string(_first(sources, "sti", "alist", "singers")), "", ""


def _language(sources: tuple) -> str:
    language = _first(sources, "language")
    if not language:
        langs = _first(sources, "lang")
        language = langs[0] if isinstance(langs, list) and langs else langs
    return _text(language)


def _is_explicit(sources: tuple) -> bool:
    return str(_first(sources, "parental_warning", "pw")) == "1"


def _images(sources: tuple) -> dict:
    """Prefer real per-size fields; derive the missing sizes from whichever URL exists."""
    base = _first(sources, "atw", "artwork_web", "aw", "artwork", "artwork_large", "artwork_medium")
    derived = artwork_urls(base)
    return {"urls": {
        "large_artwork": _text(_first(sources, "artwork_large", "artwork_medium")) or derived["large_artwork"],
        "medium_artwork": _text(_first(sources, "artwork_web", "atw")) or derived["medium_artwork"],
        "small_artwork": _text(_first(sources, "artwork")) or derived["small_artwork"],
    }}


def _album_fields(entity: dict, values: dict) -> tuple[str, str, str]:
    """(title, seokey, id) of the album a track belongs to."""
    album = values.get("album") or entity.get("album")
    if isinstance(album, list):
        album = album[0] if album and isinstance(album[0], dict) else {}
    if not isinstance(album, dict):
        album = {}
    sources = (entity, album)
    return (
        _text(_first(sources, "album_title") or album.get("name") or album.get("title")),
        _text(_first(sources, "albumseokey", "album_seokey") or album.get("seokey")),
        _text(_first(sources, "album_id")),
    )


def encrypted_stream(entity: dict) -> str:
    """The encrypted 'medium' stream link the entity carries, if any."""
    if not isinstance(entity, dict):
        return ""
    for urls in (entity.get("urls"), entity_values(entity).get("stream_url")):
        medium = urls.get("medium") if isinstance(urls, dict) else None
        if isinstance(medium, dict) and isinstance(medium.get("message"), str):
            return medium["message"]
    return ""


def song_row_from_entity(entity, require_artwork: bool = True) -> dict | None:
    """A song row from any list/search entity, or None when it lacks seokey, title or
    (unless `require_artwork=False`) artwork; the caller then falls back to songDetail."""
    if not isinstance(entity, dict):
        return None
    values = entity_values(entity)
    sources = (entity, values)
    seokey = _text(_first(sources, "seokey", "seo"))
    title = _text(_first(sources, "track_title", "title", "name", "ti"))
    images = _images(sources)
    if not seokey or not title:
        return None
    if require_artwork and not any(images["urls"].values()):
        return None
    if _text(_first(sources, "entity_type", "ty")).upper() in ("AL", "ALBUM", "PL", "PLAYLIST", "AR", "ARTIST"):
        return None
    names, artist_seokeys, artist_ids = _artist_fields(sources)
    album, album_seokey, album_id = _album_fields(entity, values)
    return {
        "seokey": seokey,
        "album_seokey": album_seokey,
        "track_id": _text(_first(sources, "track_id", "entity_id", "id", "iid")),
        "title": title,
        "artists": names,
        "artist_seokeys": artist_seokeys,
        "artist_ids": artist_ids,
        "artist_image": "",
        "album": album,
        "album_id": album_id,
        "duration": _text(_first(sources, "duration")),
        "popularity": _text(_first(sources, "popularity")),
        "genres": "",
        "is_explicit": _is_explicit(sources),
        "language": _language(sources),
        "label": "",
        "release_date": _text(_first(sources, "release_date")),
        "play_count": _text(_first(sources, "play_ct")),
        "favorite_count": _text(_first(sources, "total_favourite_count", "favorite_count")),
        "song_url": f"https://gaana.com/song/{seokey}",
        "album_url": f"https://gaana.com/album/{album_seokey}" if album_seokey else "",
        "images": images,
        "stream_urls": {"urls": {}},
        "lite": True,
    }


def album_row_from_entity(entity, require_artwork: bool = True) -> dict | None:
    """An album row (format_json_albums(info=False) keys) from a list/search entity."""
    if not isinstance(entity, dict):
        return None
    values = entity_values(entity)
    sources = (entity, values)
    seokey = _text(_first(sources, "seokey", "seo"))
    title = _text(_first(sources, "title", "name", "ti"))
    images = _images(sources)
    if not seokey or not title:
        return None
    if require_artwork and not any(images["urls"].values()):
        return None
    names, artist_seokeys, artist_ids = _artist_fields(sources)
    return {
        "seokey": seokey,
        "album_id": _text(_first(sources, "album_id", "entity_id", "id", "iid")),
        "title": title,
        "artists": names,
        "artist_seokeys": artist_seokeys,
        "artist_ids": artist_ids,
        "duration": _text(_first(sources, "duration")),
        "is_explicit": _is_explicit(sources),
        "language": _language(sources),
        "label": _text(_first(sources, "recordlevel")),
        "track_count": _text(_first(sources, "trackcount", "track_count")),
        "release_date": _text(_first(sources, "release_date")),
        "play_count": _text(_first(sources, "al_play_ct", "play_ct")),
        "favorite_count": _text(_first(sources, "favorite_count")),
        "album_url": f"https://gaana.com/album/{seokey}",
        "images": images,
        "lite": True,
    }


def artist_row_from_entity(entity) -> dict | None:
    """An artist row (format_json_artists(info=False) keys) from a search entity."""
    if not isinstance(entity, dict):
        return None
    values = entity_values(entity)
    sources = (entity, values)
    seokey = _text(_first(sources, "seokey", "seo"))
    name = _text(_first(sources, "name", "ti", "title"))
    if not seokey or not name:
        return None
    return {
        "seokey": seokey,
        "artist_id": _text(_first(sources, "artist_id", "entity_id", "id", "iid")),
        "name": name,
        "song_count": _text(_first(sources, "songs", "song_count")),
        "album_count": _text(_first(sources, "albums", "album_count")),
        "favorite_count": _text(_first(sources, "favorite_count")),
        "artist_url": f"https://gaana.com/artist/{seokey}",
        "images": {"urls": artwork_urls(_first(sources, "atw", "aw", "artwork"))},
        "lite": True,
    }


def search_items(result) -> list:
    """The hits (`gd`) of a Gaana search response: the first result group that has any."""
    if not isinstance(result, dict):
        return []
    groups = result.get("gr")
    if not isinstance(groups, list):
        return []
    for group in groups:
        items = group.get("gd") if isinstance(group, dict) else None
        if isinstance(items, list) and items:
            return [item for item in items if isinstance(item, dict)]
    return []


def page_slice(rows: list, limit: int, page: int) -> list:
    offset = (max(1, page) - 1) * limit
    return rows[offset:offset + limit]
