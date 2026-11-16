"""Pure unit tests: normalisation, LRC parsing, stream expiry, caching."""

import time

from app.integrations.gaanapy import normalize as n
from app.services.cache import MemoryCache
from app.services.catalog_service import sanitize_query
from app.services.lyrics_service import parse_lrc


def test_artist_refs_zip_when_counts_match():
    refs = n.artist_refs("Lil Nas X, Jack Harlow", "lil-nas-x, jack-harlow", "1764015, 817522")
    assert [(r.name, r.id, r.numeric_id) for r in refs] == [
        ("Lil Nas X", "lil-nas-x", "1764015"), ("Jack Harlow", "jack-harlow", "817522")]


def test_artist_refs_match_by_slug_when_counts_differ():
    refs = n.artist_refs("Babyface, Jack Harlow", "jack-harlow", "817522")
    assert [(r.name, r.id, r.numeric_id) for r in refs] == [("Babyface", None, None), ("Jack Harlow", "jack-harlow", "817522")]


def test_artwork_fills_missing_sizes():
    art = n.artwork({"images": {"urls": {"large_artwork": "", "medium_artwork": "m.jpg", "small_artwork": ""}}})
    assert (art.small, art.medium, art.large) == ("m.jpg", "m.jpg", "m.jpg")


def test_track_without_streams_is_not_playable():
    t = n.track({"seokey": "x", "title": "X", "stream_urls": {"urls": {"high_quality": ""}}})
    assert t.playable is False


def test_stream_expiry_parsed():
    url = "https://cdn/hls/1/2/3/128.mp4.master.m3u8?hdnts=st=1794816981~exp=1794831381~acl=/hls/*~hmac=ab"
    assert int(n.stream_expiry(url).timestamp()) == 1794831381
    assert n.stream_expiry("https://cdn/no-token.m3u8") is None


def test_parse_lrc_handles_multi_stamps_and_ignores_metadata():
    lines = parse_lrc("[ar:Someone]\n[00:10.5]B\n[00:01.00][00:20.00]A\nnot a line")
    assert [(line.time_ms, line.text) for line in lines] == [(1000, "A"), (10500, "B"), (20000, "A")]


def test_sanitize_query():
    assert sanitize_query("  héllo   wörld!! ") == "h llo w rld"
    assert sanitize_query("AC/DC & friends") == "AC DC & friends"


async def test_memory_cache_expiry():
    c = MemoryCache()
    await c.set("a", {"x": 1}, 1)
    assert await c.get("a") == {"x": 1}
    c._data["a"] = (time.monotonic() - 1, c._data["a"][1])
    assert await c.get("a") is None
