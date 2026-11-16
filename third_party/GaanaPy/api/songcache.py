"""Local fix: remember formatted song details so lists don't re-request every song.

An entry lives for GAANA_SONG_CACHE_SECONDS (default 1800), but never past its stream
links' own expiry (Akamai `exp=` token) minus a safety margin, so a cached song can
always still be played. Bounded by GAANA_SONG_CACHE_SIZE entries (least recently used
dropped first).
"""

import os
import re
import time
from collections import OrderedDict

_EXP = re.compile(r"exp=(\d+)")
STREAM_MARGIN_SECONDS = 900


def _stream_expiry(records: list) -> float | None:
    """Earliest stream-token expiry (epoch seconds) across the records, if any."""
    found = []
    for record in records:
        urls = ((record or {}).get("stream_urls") or {}).get("urls") or {}
        for url in urls.values():
            match = _EXP.search(url) if isinstance(url, str) else None
            if match:
                found.append(float(match.group(1)))
    return min(found) if found else None


class SongCache:
    def __init__(self, ttl: float | None = None, max_items: int | None = None, clock=time.time):
        self.ttl = float(os.getenv("GAANA_SONG_CACHE_SECONDS", "1800")) if ttl is None else ttl
        self.max_items = int(os.getenv("GAANA_SONG_CACHE_SIZE", "5000")) if max_items is None else max_items
        self._clock = clock
        self._data: OrderedDict[str, tuple[float, list]] = OrderedDict()

    def get_many(self, seokeys: list) -> dict:
        now = self._clock()
        out = {}
        for seokey in seokeys:
            item = self._data.get(seokey)
            if item is None:
                continue
            expires, records = item
            if expires <= now:
                self._data.pop(seokey, None)
                continue
            self._data.move_to_end(seokey)
            out[seokey] = records
        return out

    def put(self, seokey: str, records: list) -> None:
        if self.ttl <= 0 or self.max_items <= 0 or not records:
            return
        now = self._clock()
        expires = now + self.ttl
        stream_exp = _stream_expiry(records)
        if stream_exp is not None:
            expires = min(expires, stream_exp - STREAM_MARGIN_SECONDS)
        if expires <= now:
            return
        self._data[seokey] = (expires, records)
        self._data.move_to_end(seokey)
        while len(self._data) > self.max_items:
            self._data.popitem(last=False)
