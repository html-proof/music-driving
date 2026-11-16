"""Local fix: search and list rows are built from the list payload itself.

Offline: Gaana's answers are recorded responses (tests/fixtures/search_*.json, recorded
from https://gaana.com/apiv2?...&type=search) or small hand-written payloads.
"""

import json
from pathlib import Path

import pytest

from api.entities import (
    album_row_from_entity, artist_row_from_entity, artwork_urls, song_row_from_entity,
)
from api.errors import BlockedError, UpstreamUnavailable
from api.gaanapy import GaanaPy

FIXTURES = Path(__file__).parent / "fixtures"
SONG_KEYS = {
    "seokey", "album_seokey", "track_id", "title", "artists", "artist_seokeys", "artist_ids",
    "artist_image", "album", "album_id", "duration", "popularity", "genres", "is_explicit",
    "language", "label", "release_date", "play_count", "favorite_count", "song_url",
    "album_url", "images", "stream_urls",
}


def recorded(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


async def gaana_answering(answer):
    """A real GaanaPy whose Gaana calls are answered by `answer(url, kwargs)`."""
    g = GaanaPy()
    await g.aiohttp.close()
    g.calls = []

    async def stub(method, url, **kwargs):
        g.calls.append((url, kwargs))
        result = answer(url, kwargs)
        if isinstance(result, Exception):
            raise result
        return result

    g._request_now = stub
    return g


def song_detail(seokey: str) -> dict:
    return {"tracks": [{
        "seokey": seokey, "track_id": "1", "track_title": seokey.title(),
        "artist": [{"name": "A", "seokey": "a", "artist_id": "7"}],
        "artwork": "https://img/size_s.jpg", "urls": {},
    }]}


# --- artwork sizes --------------------------------------------------------------------

@pytest.mark.parametrize("url,large,small", [
    ("https://a10.gaanacdn.com/gn_img/albums/d4/41/size_m_1712905431.jpg",
     "https://a10.gaanacdn.com/gn_img/albums/d4/41/size_l_1712905431.jpg",
     "https://a10.gaanacdn.com/gn_img/albums/d4/41/size_s_1712905431.jpg"),
    ("https://cdn.gaana.com/images/test/size_s.jpg",
     "https://cdn.gaana.com/images/test/size_l.jpg",
     "https://cdn.gaana.com/images/test/size_s.jpg"),
    ("https://a10.gaanacdn.com/images/playlists/27/1038627/crop_175x175_1793105696_1038627.jpg",
     "https://a10.gaanacdn.com/images/playlists/27/1038627/crop_175x175_1793105696_1038627.jpg",
     "https://a10.gaanacdn.com/images/playlists/27/1038627/crop_175x175_1793105696_1038627.jpg"),
])
def test_artwork_sizes_handle_timestamped_urls(url, large, small):
    sizes = artwork_urls(url)
    assert sizes["large_artwork"] == large
    assert sizes["small_artwork"] == small


def test_artwork_sizes_of_nothing_are_empty():
    assert artwork_urls(None) == {"large_artwork": "", "medium_artwork": "", "small_artwork": ""}


@pytest.mark.asyncio
async def test_recorded_chart_artwork_gets_real_sizes():
    g = await gaana_answering(lambda url, kw: recorded("charts_top.json"))
    charts = await g.get_charts(5)
    first = charts[0]
    assert first["seokey"] == "gaana-dj-hindi-top-50-1"
    assert first["images"]["urls"]["large_artwork"].endswith("/size_l_1793105696.jpg")
    assert first["images"]["urls"]["small_artwork"].endswith("/size_s_1793105696.jpg")


# --- the shared entity mapper ---------------------------------------------------------

def test_mapper_reads_flat_song_detail_shape():
    row = song_row_from_entity({
        "seokey": "tumhiho", "track_id": 944286, "track_title": "Tum Hi Ho",
        "artist": [{"name": "Mithoon", "seokey": "mithoon", "artist_id": "1"},
                   {"name": "Arijit Singh", "seokey": "arijit-singh", "artist_id": 2}],
        "album_title": "Aashiqui 2", "albumseokey": "aashiqui-2", "album_id": "5",
        "duration": "262", "language": "Hindi", "parental_warning": 0,
        "artwork": "https://img/size_s.jpg", "artwork_web": "https://img/size_m.jpg",
        "artwork_large": "https://img/size_l.jpg",
    })
    assert row["track_id"] == "944286"
    assert row["artists"] == "Mithoon, Arijit Singh"
    assert row["artist_seokeys"] == "mithoon, arijit-singh"
    assert row["artist_ids"] == "1, 2"
    assert (row["album"], row["album_seokey"], row["album_id"]) == ("Aashiqui 2", "aashiqui-2", "5")
    assert row["duration"] == "262"
    assert row["images"]["urls"] == {
        "large_artwork": "https://img/size_l.jpg",
        "medium_artwork": "https://img/size_m.jpg",
        "small_artwork": "https://img/size_s.jpg",
    }
    assert row["lite"] is True and set(row) == SONG_KEYS | {"lite"}


def test_mapper_reads_entity_info_shape():
    row = song_row_from_entity({
        "seokey": "song-x", "entity_id": "80692668", "name": "Song X", "language": "Tamil",
        "entity_type": "TR",
        "artwork": "https://img/crop_175x175_1.jpg",
        "atw": "https://img/gn/size_m_1793105696.jpg",
        "artwork_medium": "https://img/crop_480x480_1.jpg",
        "entity_info": [
            {"key": "artist", "value": [{"name": "Anirudh", "seokey": "anirudh", "artist_id": "9"}]},
            {"key": "album", "value": [{"album_id": "3", "album_seokey": "alb", "name": "Alb"}]},
            {"key": "duration", "value": 201},
            {"key": "parental_warning", "value": 1},
        ],
    })
    assert row["track_id"] == "80692668"
    assert row["title"] == "Song X"
    assert (row["artists"], row["artist_seokeys"], row["artist_ids"]) == ("Anirudh", "anirudh", "9")
    assert (row["album"], row["album_seokey"], row["album_id"]) == ("Alb", "alb", "3")
    assert row["duration"] == "201"
    assert row["is_explicit"] is True
    assert row["images"]["urls"]["large_artwork"] == "https://img/crop_480x480_1.jpg"
    assert row["images"]["urls"]["medium_artwork"] == "https://img/gn/size_m_1793105696.jpg"


@pytest.mark.parametrize("entity", [
    {"seokey": "x", "track_title": "X"},                         # no artwork
    {"seokey": "x", "artwork": "https://img/size_s.jpg"},        # no title
    {"track_title": "X", "artwork": "https://img/size_s.jpg"},   # no seokey
    {"seokey": "x", "name": "X", "atw": "https://i", "entity_type": "AL"},  # an album
    "not-a-dict",
])
def test_mapper_returns_none_when_a_row_cannot_be_built(entity):
    assert song_row_from_entity(entity) is None


def test_album_and_artist_rows_from_search_hits():
    album = album_row_from_entity({"seo": "aashiqui-2", "id": 501, "ti": "Aashiqui 2",
                                   "aw": "https://img/size_m_5.jpg", "sti": "Mithoon,Arijit Singh",
                                   "language": "Hindi"})
    assert album["album_id"] == "501" and album["title"] == "Aashiqui 2"
    assert album["artists"] == "Mithoon, Arijit Singh"
    assert album["images"]["urls"]["large_artwork"] == "https://img/size_l_5.jpg"
    assert album["lite"] is True

    artist = artist_row_from_entity({"seo": "arijit-singh", "id": 2, "ti": "Arijit Singh",
                                     "aw": "https://img/size_m_9.jpg"})
    assert artist["artist_id"] == "2" and artist["name"] == "Arijit Singh"
    assert artist["images"]["urls"]["small_artwork"] == "https://img/size_s_9.jpg"


# --- search ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_song_search_rows_come_from_the_recorded_hits_in_one_request():
    g = await gaana_answering(lambda url, kw: recorded("search_tracks_tum_hi_ho.json"))

    rows = await g.search_songs("Tum Hi Ho", 10)

    assert len(g.calls) == 1  # no songDetail per row
    assert len(rows) == 10
    first = rows[0]
    assert first["seokey"] == "tumhiho"
    assert first["track_id"] == "944286"
    assert first["title"] == "Tum Hi Ho"
    assert first["artists"] == "Mithoon, Arijit Singh"
    assert first["artist_seokeys"] == "" and first["artist_ids"] == ""
    assert first["language"] == "Hindi"
    assert first["duration"] == "" and first["album"] == ""
    assert first["stream_urls"] == {"urls": {}}
    assert first["lite"] is True
    assert first["images"]["urls"] == {
        "large_artwork": "https://a10.gaanacdn.com/gn_img/albums/d41WjnWPLq/41Wjz1LOWP/size_l_1712905431.jpg",
        "medium_artwork": "https://a10.gaanacdn.com/gn_img/albums/d41WjnWPLq/41Wjz1LOWP/size_m_1712905431.jpg",
        "small_artwork": "https://a10.gaanacdn.com/gn_img/albums/d41WjnWPLq/41Wjz1LOWP/size_s_1712905431.jpg",
    }
    assert set(first) == SONG_KEYS | {"lite"}
    # Ids are Gaana's own, in Gaana's order - never positions.
    hits = recorded("search_tracks_tum_hi_ho.json")["gr"][0]["gd"]
    assert [r["seokey"] for r in rows] == [h["seo"] for h in hits[:10]]
    assert [r["track_id"] for r in rows] == [str(h["id"]) for h in hits[:10]]


@pytest.mark.asyncio
async def test_search_pages_are_slices_of_the_first_result_page():
    g = await gaana_answering(lambda url, kw: recorded("search_tracks_tum_hi_ho.json"))
    hits = recorded("search_tracks_tum_hi_ho.json")["gr"][0]["gd"]  # 41 hits

    page2 = await g.search_songs("Tum Hi Ho", 10, page=2)
    page5 = await g.search_songs("Tum Hi Ho", 10, page=5)
    past_end = await g.search_songs("Tum Hi Ho", 10, page=6)

    assert [r["seokey"] for r in page2] == [h["seo"] for h in hits[10:20]]
    assert [r["seokey"] for r in page5] == [h["seo"] for h in hits[40:41]]
    assert past_end == {"error": "Unable to find any results!"}
    assert len(g.calls) == 1  # later pages are served from the cached response


@pytest.mark.asyncio
async def test_native_script_query_results():
    g = await gaana_answering(lambda url, kw: recorded("search_tracks_malare.json"))

    rows = await g.search_songs("മലരേ", 5)

    assert g.calls[0][1]["params"]["keyword"] == "മലരേ"
    assert rows[0]["seokey"] == "malare"
    assert rows[0]["artists"] == "S. Janaki, Vidyasagar, S. P. Balasubrahmanyam"


@pytest.mark.asyncio
async def test_album_and_artist_search_are_one_request_each():
    hits = {"gr": [{"ty": "Album", "gd": [
        {"seo": "aashiqui-2", "id": 501, "ti": "Aashiqui 2", "aw": "https://img/size_m.jpg", "language": "Hindi"},
        {"seo": "", "ti": "no seokey"},
    ]}]}
    g = await gaana_answering(lambda url, kw: hits)

    albums = await g.search_albums("Aashiqui", 10)
    artists = await g.search_artists("Aashiqui", 10)

    assert [a["seokey"] for a in albums] == ["aashiqui-2"]
    assert [a["seokey"] for a in artists] == ["aashiqui-2"]
    assert [c[1]["params"]["secType"] for c in g.calls] == ["album", "artist"]


# --- lists ----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_trending_rows_come_from_the_payload_when_it_has_the_fields():
    entity = {"seokey": "s1", "entity_id": "1", "name": "S1", "atw": "https://img/size_m.jpg",
              "entity_type": "TR", "language": "Hindi"}
    g = await gaana_answering(lambda url, kw: {"entities": [entity] * 1 + [dict(entity, seokey="s2")]})

    rows = await g.get_trending("Hindi", 10)

    assert [r["seokey"] for r in rows] == ["s1", "s2"]
    assert len(g.calls) == 1


@pytest.mark.asyncio
async def test_partial_fan_out_failure_keeps_the_successes():
    def answer(url, kw):
        if "miscTrendingSongs" in url:
            return {"entities": [{"seokey": "a"}, {"seokey": "b"}, {"seokey": "c"}]}
        if url.endswith("=b"):
            return BlockedError(403, 120)
        return song_detail(url.rsplit("=", 1)[1])

    g = await gaana_answering(answer)
    g.breaker.trip = lambda *a, **k: 120  # the stub raises the block itself

    rows = await g.get_trending("Hindi", 10)

    assert [r["seokey"] for r in rows] == ["a", "c"]
    assert rows[0]["stream_urls"]["urls"]["medium_quality"] == ""  # full songDetail row


@pytest.mark.asyncio
async def test_fan_out_where_everything_is_blocked_reports_the_block():
    def answer(url, kw):
        if "miscTrendingSongs" in url:
            return {"entities": [{"seokey": "a"}, {"seokey": "b"}]}
        return UpstreamUnavailable("timeout") if url.endswith("=a") else BlockedError(403, 60)

    g = await gaana_answering(answer)

    with pytest.raises(BlockedError):
        await g.get_trending("Hindi", 10)


@pytest.mark.asyncio
async def test_fallback_lookups_are_capped_at_limit():
    def answer(url, kw):
        if "miscTrendingSongs" in url:
            return {"entities": [{"seokey": f"s{i}"} for i in range(30)]}
        return song_detail(url.rsplit("=", 1)[1])

    g = await gaana_answering(answer)

    rows = await g.get_trending("Hindi", 5)

    assert [r["seokey"] for r in rows] == ["s0", "s1", "s2", "s3", "s4"]
    assert len(g.calls) == 1 + 5


def _new_release(kind: str, i: int) -> dict:
    return {"seokey": f"{kind.lower()}-{i}", "entity_id": str(i), "name": f"{kind} {i}",
            "entity_type": kind, "atw": "https://img/size_m.jpg", "language": "Tamil"}


@pytest.mark.asyncio
async def test_new_releases_limit_applies_to_each_type():
    entities = [_new_release("AL", i) for i in range(12)] + [_new_release("TR", i) for i in range(12)]
    g = await gaana_answering(lambda url, kw: {"entities": entities})

    result = await g.get_new_releases("Tamil", 5)

    assert [t["seokey"] for t in result["tracks"]] == [f"tr-{i}" for i in range(5)]
    assert [a["seokey"] for a in result["albums"]] == [f"al-{i}" for i in range(5)]
    assert len(g.calls) == 1


@pytest.mark.asyncio
async def test_new_releases_with_one_type_only_gives_an_empty_list_for_the_other():
    g = await gaana_answering(lambda url, kw: {"entities": [_new_release("AL", i) for i in range(3)]})

    result = await g.get_new_releases("Tamil", 10)

    assert result["tracks"] == []
    assert len(result["albums"]) == 3


@pytest.mark.asyncio
async def test_new_release_albums_without_artwork_fall_back_to_album_detail():
    def answer(url, kw):
        if "miscNewRelease" in url:
            return {"entities": [{"seokey": "bare", "entity_type": "AL"}]}
        return {"album": {"seokey": "bare", "title": "Bare", "artwork": "https://img/size_s.jpg",
                          "artist": [{"name": "A", "seokey": "a", "artist_id": "1"}]}}

    g = await gaana_answering(answer)

    result = await g.get_new_releases("Tamil", 10)

    assert result["albums"][0]["title"] == "Bare"
    assert result["albums"][0]["artist_seokeys"] == "a"


@pytest.mark.asyncio
async def test_playlist_is_limited_and_built_from_its_tracks():
    tracks = [{"seokey": f"t{i}", "track_title": f"T{i}", "artwork": "https://img/size_s.jpg",
               "artist": [{"name": "A", "seokey": "a", "artist_id": "1"}]} for i in range(60)]
    g = await gaana_answering(lambda url, kw: {"count": "60", "tracks": tracks, "error": "SUCCESS"})

    default = await g.get_playlist_info("top-50")
    three = await g.get_playlist_info("top-50", 3)

    assert len(default) == 50
    assert [t["seokey"] for t in three] == ["t0", "t1", "t2"]
    assert len(g.calls) == 1


@pytest.mark.asyncio
async def test_album_info_fetches_album_detail_once_and_uses_the_album_artists():
    detail = {
        "album": {"seokey": "alb", "title": "Alb", "artwork": "https://img/size_s_1712905431.jpg",
                  "artist": [{"name": "Composer", "seokey": "composer", "artist_id": "11"}]},
        "tracks": [{"seokey": "t1", "track_title": "T1", "artwork": "https://img/size_s.jpg",
                    "artist": [{"name": "Singer", "seokey": "singer", "artist_id": "22"}]}],
    }
    g = await gaana_answering(lambda url, kw: detail)

    [album] = await g.get_album_info(["alb"], True)

    assert len(g.calls) == 1
    assert (album["artists"], album["artist_seokeys"], album["artist_ids"]) == ("Composer", "composer", "11")
    assert album["images"]["urls"]["large_artwork"] == "https://img/size_l_1712905431.jpg"
    assert [t["seokey"] for t in album["tracks"]] == ["t1"]
    assert album["tracks"][0]["artist_seokeys"] == "singer"


@pytest.mark.asyncio
async def test_album_artist_keys_are_not_borrowed_from_a_different_first_track_artist():
    detail = {
        "album": {"seokey": "alb", "title": "Alb", "artist": [{"name": "Composer"}]},
        "tracks": [{"seokey": "t1", "artist": [{"name": "Singer", "seokey": "singer", "artist_id": "22"}]}],
    }
    g = await gaana_answering(lambda url, kw: detail)

    [album] = await g.get_album_info(["alb"], False)

    assert album["artists"] == "Composer"
    assert album["artist_seokeys"] == "" and album["artist_ids"] == ""


@pytest.mark.asyncio
async def test_artist_top_tracks_come_from_the_track_list():
    def answer(url, kw):
        if "artistDetail" in url:
            return {"artist": [{"seokey": "arijit-singh", "artist_id": "2", "name": "Arijit Singh",
                                "atw": "https://img/size_m.jpg"}]}
        return {"entities": [_new_release("TR", i) for i in range(7)]}

    g = await gaana_answering(answer)

    [artist] = await g.get_artist_info(["arijit-singh"], True, 3, 2)

    assert [t["seokey"] for t in artist["top_tracks"]] == ["tr-3", "tr-4", "tr-5"]
    assert artist["total_tracks"] == 7
    assert len(g.calls) == 2
