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


def test_track_reported_without_streams_is_not_playable():
    # A full song record whose stream slots are all empty: Gaana has no stream for it.
    t = n.track({"seokey": "x", "title": "X", "stream_urls": {"urls": {"high_quality": ""}}})
    assert t.playable is False


def test_lite_row_is_playable_with_unknown_duration():
    row = {"seokey": "tumhiho", "track_id": "944286", "title": "Tum Hi Ho", "artists": "Mithoon, Arijit Singh",
           "artist_seokeys": "", "artist_ids": "", "album": "", "album_seokey": "", "album_id": "",
           "duration": "", "language": "Hindi", "stream_urls": {"urls": {}}, "lite": True,
           "images": {"urls": {"small_artwork": "https://a10.gaanacdn.com/x/size_s_1.jpg",
                               "medium_artwork": "https://a10.gaanacdn.com/x/size_m_1.jpg",
                               "large_artwork": "https://a10.gaanacdn.com/x/size_l_1.jpg"}}}
    t = n.track(row)
    assert t.playable is True and t.duration == 0 and t.album is None
    assert [(a.name, a.id, a.numeric_id) for a in t.artists] == [("Mithoon", None, None), ("Arijit Singh", None, None)]
    assert t.artwork.large.endswith("size_l_1.jpg") and t.track_id == "944286"
    assert n.stream_urls(row) == {}
    # No stream information at all is "unknown", not "unstreamable".
    assert n.track({"seokey": "y", "title": "Y"}).playable is True


def test_records_dedupe_by_seokey():
    rows = n.records([{"seokey": "a", "title": "1"}, {"seokey": "b"}, {"seokey": "a", "title": "2"}, {"x": 1}, "junk"])
    assert [(r["seokey"], r.get("title")) for r in rows] == [("a", "1"), ("b", None)]


def test_stream_expiry_parsed():
    url = "https://cdn/hls/1/2/3/128.mp4.master.m3u8?hdnts=st=1794816981~exp=1794831381~acl=/hls/*~hmac=ab"
    assert int(n.stream_expiry(url).timestamp()) == 1794831381
    assert n.stream_expiry("https://cdn/no-token.m3u8") is None


def test_parse_lrc_handles_multi_stamps_and_ignores_metadata():
    lines = parse_lrc("[ar:Someone]\n[00:10.5]B\n[00:01.00][00:20.00]A\nnot a line")
    assert [(line.time_ms, line.text) for line in lines] == [(1000, "A"), (10500, "B"), (20000, "A")]


def test_sanitize_query_keeps_every_script():
    assert sanitize_query("  h\u00e9llo   w\u00f6rld!! ") == "h\u00e9llo w\u00f6rld!!"
    assert sanitize_query("AC/DC & friends") == "AC/DC & friends"
    assert sanitize_query(" \u0d2e\u0d32\u0d30\u0d47\t\n ") == "\u0d2e\u0d32\u0d30\u0d47"  # മലരേ
    # A control character becomes a space; a bidi mark is dropped.
    assert sanitize_query("tum\x00hi\u200fho") == "tum hiho"
    assert sanitize_query("\u0d28\u0d4d\u200d\u0d31") == "\u0d28\u0d4d\u200d\u0d31"  # ZWJ is Malayalam spelling
    assert sanitize_query("\x07 \x1b ") == ""
    assert len(sanitize_query("a" * 500)) == 200


async def test_memory_cache_expiry():
    c = MemoryCache()
    await c.set("a", {"x": 1}, 1)
    assert await c.get("a") == {"x": 1}
    c._data["a"] = (time.monotonic() - 1, c._data["a"][1])
    assert await c.get("a") is None


def test_provider_remembers_lite_rows_without_letting_them_replace_streams():
    from app.integrations.gaanapy.provider import GaanaProvider

    lite = {"seokey": "a", "track_id": "1", "title": "A", "artists": "X", "stream_urls": {"urls": {}}, "lite": True}
    full = {"seokey": "a", "track_id": "1", "title": "A", "artists": "X", "duration": "200",
            "stream_urls": {"urls": {"high_quality": "https://cdn.test/a/high.m3u8"}}}
    album = {"seokey": "al", "album_id": "9", "title": "Album", "lite": True}
    provider = GaanaProvider(client=None)
    provider._harvest([lite, album])
    known = provider.known_track("a")
    assert known.track.title == "A" and known.streams == {}  # metadata now, stream at play time
    assert provider.known_track("al") is None  # only song rows are remembered
    provider._harvest([full])
    provider._harvest([lite])  # a later lite listing keeps the record that has streams
    known = provider.known_track("a")
    assert known.streams and known.track.duration == 200
