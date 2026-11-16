"""Lyrics via LRCLIB (https://lrclib.net), a free, open lyrics database with time-synced LRC.

LRCLIB's lyrics are crowd-sourced; its API is free to use without a key and asks clients
to send an identifying User-Agent. Synced timestamps are only returned when LRCLIB has
them: plain lyrics are never given invented timestamps.
"""

import logging
import re

import httpx

from app.integrations.errors import ProviderUnavailable
from app.schemas.lyrics import LyricLine, Lyrics
from app.schemas.music import Track
from app.services.cache import Cache

log = logging.getLogger(__name__)

_LRC_LINE = re.compile(r"^\[(\d+):(\d+(?:\.\d+)?)\](.*)$")


def parse_lrc(text: str) -> list[LyricLine]:
    lines: list[LyricLine] = []
    for raw in text.splitlines():
        raw = raw.strip()
        stamps = []
        # A line can carry several timestamps: [00:12.00][01:30.00]chorus
        while (m := _LRC_LINE.match(raw)) is not None:
            stamps.append(int(m.group(1)) * 60 + float(m.group(2)))
            raw = m.group(3)
        for ts in stamps:
            lines.append(LyricLine(time_ms=int(round(ts * 1000)), text=raw.strip()))
    lines.sort(key=lambda line: line.time_ms)
    return lines


def _primary_artist(track: Track) -> str:
    return track.artists[0].name if track.artists else ""


def _clean_title(title: str) -> str:
    # "Song (From \"Movie\")" / "Song - Remix" -> better LRCLIB matches for the base search.
    return re.sub(r"\s*[\(\[].*?[\)\]]", "", title).strip() or title


class LyricsService:
    def __init__(self, base_url: str, user_agent: str, cache: Cache, enabled: bool = True,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.enabled = enabled
        self.cache = cache
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"), timeout=15, headers={"User-Agent": user_agent}, transport=transport
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def for_track(self, track: Track) -> Lyrics:
        empty = Lyrics(song_id=track.id, available=False, synced=False, source="lrclib")
        if not self.enabled:
            return empty
        key = f"lyrics:{track.id}"
        hit = await self.cache.get(key)
        if hit is not None:
            return Lyrics.model_validate(hit)
        try:
            record = await self._match(track)
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"Lyrics provider unreachable: {exc}") from exc
        result = self._to_lyrics(track.id, record) if record else empty
        # Cache misses for less time so newly contributed lyrics show up.
        await self.cache.set(key, result.model_dump(mode="json"), 86400 if result.available else 3600)
        return result

    async def _match(self, track: Track) -> dict | None:
        artist = _primary_artist(track)
        params = {"track_name": track.title, "artist_name": artist}
        if track.album:
            params["album_name"] = track.album.title
        if track.duration:
            params["duration"] = str(track.duration)
        # 1) exact signature lookup (LRCLIB matches duration within ±2 s)
        resp = await self._client.get("/api/get", params=params)
        if resp.status_code == 200:
            return resp.json()
        # 2) search, then pick the closest duration match from the same artist
        resp = await self._client.get(
            "/api/search", params={"track_name": _clean_title(track.title), "artist_name": artist}
        )
        if resp.status_code != 200:
            return None
        candidates = [c for c in resp.json() if isinstance(c, dict)]
        if track.duration:
            candidates = [c for c in candidates if abs(float(c.get("duration") or 0) - track.duration) <= 3]
        candidates.sort(key=lambda c: (not c.get("syncedLyrics"), abs(float(c.get("duration") or 0) - track.duration)))
        return candidates[0] if candidates else None

    def _to_lyrics(self, song_id: str, record: dict) -> Lyrics:
        synced_text = record.get("syncedLyrics") or ""
        plain_text = record.get("plainLyrics") or ""
        if record.get("instrumental"):
            return Lyrics(song_id=song_id, available=False, synced=False, instrumental=True, source="lrclib")
        lines = parse_lrc(synced_text) if synced_text else []
        if lines:
            return Lyrics(song_id=song_id, available=True, synced=True, lines=lines,
                          plain_text=plain_text or None, source="lrclib", source_id=str(record.get("id")))
        if plain_text:
            return Lyrics(song_id=song_id, available=True, synced=False, plain_text=plain_text,
                          source="lrclib", source_id=str(record.get("id")))
        return Lyrics(song_id=song_id, available=False, synced=False, source="lrclib")
