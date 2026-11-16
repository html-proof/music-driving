"""Local fix: songs already looked up are not requested from Gaana again.

Offline test (no Gaana traffic): the real request is replaced by a stub.
"""

import asyncio

from api.gaanapy import GaanaPy
from api.songcache import STREAM_MARGIN_SECONDS, SongCache


def _detail(seokey: str) -> dict:
    return {"tracks": [{"seokey": seokey, "track_title": seokey.title(), "artist": [], "urls": {}}]}


def _run(coro_factory):
    async def run():
        g = GaanaPy()
        try:
            return await coro_factory(g)
        finally:
            await g.aiohttp.close()
    return asyncio.run(run())


def test_overlapping_lists_request_each_song_once():
    requested = []

    async def scenario(g):
        async def stub(method, url, **kwargs):
            seokey = url.rsplit("=", 1)[1]
            requested.append(seokey)
            return _detail(seokey)

        g._request_now = stub
        first = await g.get_track_info(["a", "b", "c"])
        second = await g.get_track_info(["c", "d", "a"])  # e.g. the next list / hourly refresh
        return first, second

    first, second = _run(scenario)
    assert [t["seokey"] for t in first] == ["a", "b", "c"]
    assert [t["seokey"] for t in second] == ["c", "d", "a"]  # order kept
    assert requested == ["a", "b", "c", "d"]


def test_fresh_lookup_bypasses_cache():
    requested = []

    async def scenario(g):
        async def stub(method, url, **kwargs):
            requested.append(url)
            return _detail(url.rsplit("=", 1)[1])

        g._request_now = stub
        await g.get_track_info(["a"])
        await g.get_track_info(["a"], fresh=True)

    _run(scenario)
    assert len(requested) == 2


def test_failed_lookup_is_not_remembered():
    calls = []

    async def scenario(g):
        async def stub(method, url, **kwargs):
            calls.append(url)
            return {"error": "no results"} if len(calls) == 1 else _detail("a")

        g._request_now = stub
        await g.get_track_info(["a"])
        return await g.get_track_info(["a"])

    assert [t["seokey"] for t in _run(scenario)] == ["a"]
    assert len(calls) == 2


def test_entry_never_outlives_its_stream_links():
    now = [1_000_000.0]
    cache = SongCache(ttl=3600, max_items=10, clock=lambda: now[0])
    exp = int(now[0] + STREAM_MARGIN_SECONDS + 60)  # links valid ~16 minutes
    record = {"seokey": "a", "stream_urls": {"urls": {"medium_quality": f"https://x/a.mp4?hdnts=st=1~exp={exp}~acl=*"}}}
    cache.put("a", [record])
    assert cache.get_many(["a"])
    now[0] += 61
    assert cache.get_many(["a"]) == {}


def test_cache_is_bounded():
    cache = SongCache(ttl=3600, max_items=2)
    for key in "abc":
        cache.put(key, [{"seokey": key}])
    assert set(cache.get_many(["a", "b", "c"])) == {"b", "c"}
