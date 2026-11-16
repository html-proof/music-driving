"""Search in any script, search paging, provider error handling, and the multi-language
Home, against the real GaanaPy client + normaliser and recorded Gaana responses."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.config import Settings
from app.database import get_sessionmaker
from app.integrations.errors import ProviderUnavailable
from app.models import ListeningHistory
from app.repositories import catalog as catalog_repo
from app.schemas.music import ArtistRef, Track
from app.services.cache import MemoryCache
from app.services.catalog_service import CatalogService
from app.services.recommendation_service import RecommendationService
from app.services.transliterate import transliterate
from app.tests.conftest import LITE_ROUTES, auth, lite_song_rows, register

API = "/api/v1"


def searched(fake, path: str) -> list[str]:
    return [q["query"] for p, q in fake.requests if p == path]


# --- transliteration ---------------------------------------------------------------
@pytest.mark.parametrize(("text", "latin"), [
    ("മലരേ", "malare"),
    ("கொலவெறி", "kolaveri"),
    ("తెలుగు", "telugu"),
    ("तुम ही हो", "tum hi ho"),
    ("केसरिया", "kesariya"),
    ("ਪੰਜਾਬੀ", "panjabi"),
    ("ગુજરાતી", "gujarati"),
    ("ಕನ್ನಡ", "kannada"),
    ("বাংলা", "bangla"),
    ("ଓଡ଼ିଆ", "odia"),
    ("മലയാളം", "malayalam"),  # chillu + anusvara
    ("தமிழ்", "tamizh"),
    ("Arijit Singh मेरा", "arijit singh mera"),
    ("കണ്ണന്‍", "kannan"),  # old-style chillu written with ZWJ: not a word break
    ("ദർശന", "darshana"),
    ("బుట్ట బొమ్మ", "butta bomma"),
])
def test_transliteration(text, latin):
    assert transliterate(text) == latin


def test_transliteration_needs_indic_text():
    assert transliterate("Tum Hi Ho") is None
    assert transliterate("Beyoncé") is None
    assert transliterate("") is None
    assert transliterate("१२३") is None  # digits only: nothing to search differently


# --- search ------------------------------------------------------------------------
async def test_indic_query_is_searched_in_latin_too(client, fake_gaana):
    r = await client.get(f"{API}/search", params={"q": "മലരേ", "type": "songs"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["alt_query"] == "malare"
    # Both forms reach GaanaPy (URL-encoded by httpx); only the Latin one finds songs.
    assert searched(fake_gaana, "/songs/search/") == ["malare", "മലരേ"]
    expected = [row["seokey"] for row in lite_song_rows("search_malare")[:10]]
    assert [s["id"] for s in body["songs"]] == expected
    assert body["errors"] == {} and body["has_more"] == {"songs": True}
    first = body["songs"][0]
    # Lite rows: playable (stream resolved at play time), duration unknown, no invented artist ids.
    assert first["playable"] is True and first["duration"] == 0
    assert first["track_id"] == "712492" and first["language"] == "Tamil"
    assert [a["name"] for a in first["artists"]] == ["S. Janaki", "Vidyasagar", "S. P. Balasubrahmanyam"]
    assert all(a["id"] is None and a["numeric_id"] is None for a in first["artists"])
    assert first["artwork"]["large"].endswith("/R7vKX6WmrP/7vKXx7gKmr/size_l.jpg")
    assert first["artwork"]["small"].endswith("/R7vKX6WmrP/7vKXx7gKmr/size_s.jpg")


async def test_both_query_forms_are_merged_latin_first_without_duplicates(client, fake_gaana, monkeypatch):
    # The native-script search finds other (real, recorded) songs plus the same ones.
    monkeypatch.setitem(LITE_ROUTES, ("/songs/search/", "तुम ही हो"), ("search_tum_hi_ho", None))
    monkeypatch.setitem(LITE_ROUTES, ("/songs/search/", "tum hi ho"), ("search_malare", None))
    body = (await client.get(f"{API}/search", params={"q": "तुम ही हो", "type": "songs", "limit": 30})).json()
    assert body["alt_query"] == "tum hi ho"
    ids = [s["id"] for s in body["songs"]]
    latin = [r["seokey"] for r in lite_song_rows("search_malare")[:30]]
    assert ids == latin[:30]  # Latin results fill the page first
    assert len(ids) == len(set(ids)) == 30

    monkeypatch.setitem(LITE_ROUTES, ("/songs/search/", "tum hi ho"), ("search_tum_hi_ho", None))
    body = (await client.get(f"{API}/search", params={"q": "तुम ही हो", "type": "songs", "limit": 5,
                                                       "page": 2})).json()
    ids = [s["id"] for s in body["songs"]]
    assert ids == [r["seokey"] for r in lite_song_rows("search_tum_hi_ho")[5:10]]  # identical rows merged


async def test_type_page_and_has_more(client, fake_gaana):
    total = len(lite_song_rows("search_the_weeknd"))
    r = await client.get(f"{API}/search", params={"q": "The Weeknd", "type": "songs", "limit": 10})
    body = r.json()
    assert body["type"] == "songs" and body["page"] == 1 and body["alt_query"] is None
    assert len(body["songs"]) == 10 and body["has_more"] == {"songs": True}
    assert body["albums"] == body["artists"] == body["playlists"] == [] and body["errors"] == {}
    assert {p for p, _ in fake_gaana.requests} == {"/songs/search/"}  # only the asked-for section

    last = (total - 1) // 10 + 1
    body = (await client.get(f"{API}/search", params={"q": "The Weeknd", "type": "songs", "page": last})).json()
    assert len(body["songs"]) == total - (last - 1) * 10 and body["has_more"] == {"songs": False}
    assert ("/songs/search/", {"query": "The Weeknd", "limit": "10", "page": str(last)}) in fake_gaana.requests

    body = (await client.get(f"{API}/search", params={"q": "The Weeknd", "type": "songs", "page": last + 1})).json()
    assert body["songs"] == [] and body["errors"] == {} and body["has_more"] == {"songs": False}

    # Page 20 is the last one served.
    body = (await client.get(f"{API}/search", params={"q": "The Weeknd", "type": "songs", "page": 20,
                                                       "limit": 1})).json()
    assert len(body["songs"]) == 1 and body["has_more"] == {"songs": False}
    assert (await client.get(f"{API}/search", params={"q": "x", "page": 21})).status_code == 422
    assert (await client.get(f"{API}/search", params={"q": "x", "type": "videos"})).status_code == 422


async def test_all_sections_report_has_more(client):
    body = (await client.get(f"{API}/search", params={"q": "tyler herro", "limit": 2})).json()
    assert set(body["has_more"]) == {"songs", "albums", "artists", "playlists"}
    assert body["has_more"]["songs"] is True and body["has_more"]["playlists"] is False


async def test_empty_query_is_reported(client, fake_gaana):
    body = (await client.get(f"{API}/search", params={"q": " \u0007 "})).json()
    assert body["errors"] == {"query": "Type something to search for"}
    assert body["songs"] == [] and fake_gaana.requests == []


async def test_search_misses_are_not_remembered(client, fake_gaana):
    fake_gaana.fail[("/songs/search/", "malare")] = 404
    assert (await client.get(f"{API}/search", params={"q": "Malare", "type": "songs"})).json()["songs"] == []
    del fake_gaana.fail[("/songs/search/", "malare")]
    assert (await client.get(f"{API}/search", params={"q": "Malare", "type": "songs"})).json()["songs"]


async def test_block_starts_a_cooldown_but_gaana_errors_do_not(client, fake_gaana):
    # 502: Gaana failed on its side for this request. Reported, nothing else affected.
    fake_gaana.fail[("/songs/search/", "malare")] = "unavailable"
    body = (await client.get(f"{API}/search", params={"q": "Malare", "type": "songs"})).json()
    assert body["errors"] == {"songs": "Music provider is currently unavailable"}
    assert (await client.get(f"{API}/search", params={"q": "The Weeknd", "type": "songs"})).json()["songs"]

    # 500: a GaanaPy bug. Reported as a provider error, still no cooldown.
    fake_gaana.fail[("/songs/search/", "malare")] = "internal"
    body = (await client.get(f"{API}/search", params={"q": "Malare", "type": "songs"})).json()
    assert body["errors"] == {"songs": "Music provider error"}
    assert (await client.get(f"{API}/search", params={"q": "tum hi ho", "type": "songs"})).json()["songs"]

    # 503 blocked: nothing more is sent to GaanaPy until the cooldown is over.
    fake_gaana.fail[("/songs/search/", "malare")] = "blocked"
    body = (await client.get(f"{API}/search", params={"q": "Malare", "type": "songs"})).json()
    assert body["errors"] == {"songs": "Music provider is currently unavailable"}
    sent = len(fake_gaana.requests)
    body = (await client.get(f"{API}/search", params={"q": "something else", "type": "songs"})).json()
    assert body["errors"] == {"songs": "Music provider is currently unavailable"}
    assert len(fake_gaana.requests) == sent


async def test_gaanapy_internal_error_is_a_502_not_a_404(client, fake_gaana):
    fake_gaana.fail[("/albums/info/", "tyler-herro")] = "internal"
    r = await client.get(f"{API}/albums/tyler-herro")
    assert r.status_code == 502 and r.json() == {"detail": "Music provider error"}
    del fake_gaana.fail[("/albums/info/", "tyler-herro")]
    assert (await client.get(f"{API}/albums/tyler-herro")).status_code == 200


async def test_rejected_request_is_not_remembered_as_missing(client, fake_gaana):
    fake_gaana.fail[("/albums/info/", "tyler-herro")] = 422
    fake_gaana.fail[("/songs/info/", "tyler-herro")] = 422
    assert (await client.get(f"{API}/albums/tyler-herro")).status_code == 404
    assert (await client.get(f"{API}/songs/tyler-herro")).status_code == 404
    fake_gaana.fail.clear()
    assert (await client.get(f"{API}/albums/tyler-herro")).status_code == 200
    assert (await client.get(f"{API}/songs/tyler-herro")).status_code == 200


async def test_record_search_without_running_it(client, fake_gaana):
    h = auth(await register(client, "history"))
    r = await client.post(f"{API}/library/search-history", json={"query": "  മലരേ  "}, headers=h)
    assert r.status_code == 204, r.text
    r = await client.post(f"{API}/library/search-history", json={"query": "Tum Hi Ho"}, headers=h)
    assert r.status_code == 204
    history = (await client.get(f"{API}/library/search-history", headers=h)).json()
    assert [e["query"] for e in history] == ["Tum Hi Ho", "മലരേ"]
    assert not any(p.endswith("/search/") for p, _ in fake_gaana.requests)
    assert (await client.post(f"{API}/library/search-history", json={"query": ""}, headers=h)).status_code == 422
    assert (await client.post(f"{API}/library/search-history", json={"query": "x"})).status_code == 401


async def test_charts_are_fetched_once_for_every_use(client, fake_gaana):
    assert (await client.get(f"{API}/charts", params={"limit": 2})).json()[0]["id"] == "gaana-dj-hindi-top-50-1"
    body = (await client.get(f"{API}/search", params={"q": "hindi top", "type": "playlists"})).json()
    assert [p["id"] for p in body["playlists"]] == ["gaana-dj-hindi-top-50-1"]
    await client.get(f"{API}/home")
    await client.get(f"{API}/playlists/gaana-dj-hindi-top-50-1")
    assert fake_gaana.calls.count("/charts") == 1


# --- home ----------------------------------------------------------------------------
async def test_home_has_a_row_per_language_and_isolates_failures(client, fake_gaana):
    fake_gaana.fail[("/trending", "Tamil")] = "unavailable"
    r = await client.get(f"{API}/home", params={"languages": "Tamil,hindi"})
    assert r.status_code == 200, r.text
    home = r.json()
    rows = {s["id"]: s for s in home["sections"]}
    # The user's languages first, then the configured ones; English is the international row.
    assert home["languages"] == ["Tamil", "Hindi", "Malayalam", "Telugu", "Punjabi", "English"]
    assert "trending_tamil" not in rows and home["errors"]["trending_tamil"]
    assert home["unavailable_languages"] == ["Tamil"]
    assert rows["trending_hindi"]["title"] == "Trending in Hindi"
    assert all(t["language"] == "Hindi" and t["playable"] for t in rows["trending_hindi"]["tracks"])
    assert len(rows["trending_hindi"]["tracks"]) <= 12
    assert rows["international_hits"]["tracks"]
    # Popular artists: counted by name across trending rows, card from a one-row search.
    names = [a["name"] for a in rows["top_artists"]["artists"]]
    assert "Arijit Singh" in names and rows["top_artists"]["title"] == "Popular artists"
    arijit = next(a for a in rows["top_artists"]["artists"] if a["name"] == "Arijit Singh")
    assert arijit["id"] == "arijit-singh" and arijit["numeric_id"] == "52767"
    assert ("/artists/search/", {"query": "Arijit Singh", "limit": "1", "page": "1"}) in fake_gaana.requests
    # Popular albums: only songs that said which album they are on (the full English rows).
    album_ids = [a["id"] for a in rows["popular_albums"]["albums"]]
    english = {t["album"]["id"] for t in rows["international_hits"]["tracks"] if t["album"]}
    assert album_ids and set(album_ids) <= english and len(album_ids) == len(set(album_ids))
    # Each row is one list request (lite rows need no per-song lookups).
    assert fake_gaana.calls.count("/songs/info/") == 0
    order = [s["id"] for s in home["sections"]]
    assert order.index("trending_hindi") > order.index("charts")  # other languages after the main rows


async def test_artist_cards_need_an_exact_name_match(client, fake_gaana):
    await client.get(f"{API}/home")
    first = sum(1 for p, _ in fake_gaana.requests if p == "/artists/search/")
    home = (await client.get(f"{API}/home")).json()
    # A name the search answers with someone else (or nothing) gets no card...
    assert all(a["name"] in {"Arijit Singh"} for s in home["sections"] if s["id"] == "top_artists"
               for a in s["artists"])
    # ...and every lookup, hit or miss, is remembered: the second Home searches nothing.
    assert sum(1 for p, _ in fake_gaana.requests if p == "/artists/search/") == first


async def test_recommendation_failure_does_not_break_home(client, monkeypatch):
    h = auth(await register(client, "recs-broken"))
    await client.post(f"{API}/playback/complete", headers=h, json={"song_id": "tyler-herro", "seconds_listened": 150})

    async def broken(self, limit=30):
        raise ValueError("unexpected provider data")

    monkeypatch.setattr(RecommendationService, "recommend", broken)
    r = await client.get(f"{API}/home", headers=h, params={"languages": "English"})
    assert r.status_code == 200, r.text
    home = r.json()
    assert home["errors"]["made_for_you"] == "Unexpected error"
    assert home["sections"][0]["id"] == "recently_played"
    assert any(s["id"] == "international_hits" for s in home["sections"])


async def test_one_broken_recommendation_source_is_skipped(client, app, monkeypatch):
    h = auth(await register(client, "recs-source"))
    await client.post(f"{API}/playback/complete", headers=h, json={"song_id": "tyler-herro", "seconds_listened": 150})

    async def broken(*args, **kwargs):
        raise KeyError("bad record")

    monkeypatch.setattr(app.state.catalog, "artist_tracks", broken)
    r = await client.get(f"{API}/recommendations", headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["personalized"] is True


async def test_other_providers_songs_are_left_out(client, fake_gaana):
    h = auth(await register(client, "switched"))
    await client.post(f"{API}/playback/complete", headers=h, json={"song_id": "tyler-herro", "seconds_listened": 150})
    async with get_sessionmaker()() as db:
        played = (await db.scalars(select(ListeningHistory))).first()
        # Played earlier through Audius (before MUSIC_PROVIDER changed), more recently.
        other = await catalog_repo.upsert_song(db, "audius", Track(
            id="AbC12", title="Audius upload", artists=[ArtistRef(name="Uploader", id="handle", numeric_id="xY9")]))
        db.add(ListeningHistory(user_id=played.user_id, song_id=other.id, seconds_listened=100, completed=True,
                                played_at=datetime.now(UTC) + timedelta(minutes=1)))
        await db.commit()
    recent = (await client.get(f"{API}/library/recently-played", headers=h)).json()
    assert [t["id"] for t in recent] == ["tyler-herro"]
    home = (await client.get(f"{API}/home", headers=h, params={"languages": "English"})).json()
    assert [t["id"] for t in home["sections"][0]["tracks"]] == ["tyler-herro"]
    # Recommendation seeds are the active provider's only: no lookups for Audius ids.
    assert not any(q.get("artist_id") == "xY9" for _, q in fake_gaana.requests)
    # Where such a song is still listed (full history), it is marked unplayable.
    history = (await client.get(f"{API}/library/history", headers=h)).json()["items"]
    assert {t["track"]["id"]: t["track"]["playable"] for t in history} == {"AbC12": False, "tyler-herro": True}


# --- stale copies and deadlines -----------------------------------------------------------
class SlowProvider:
    name = "slow"

    def __init__(self):
        self.delay = 0.0
        self.calls = 0

    async def trending(self, language: str, limit: int) -> list[Track]:
        self.calls += 1
        await asyncio.sleep(self.delay)
        return [Track(id="sapphire-358", title="Sapphire")]


async def test_slow_row_falls_back_to_the_last_good_copy():
    provider = SlowProvider()
    settings = Settings(environment="test", redis_url="", home_cache_ttl_seconds=1, catalog_cache_ttl_seconds=1)
    catalog = CatalogService(provider, MemoryCache(), settings)
    tracks, stale = await catalog.trending_state("English", 12, timeout=1)
    assert [t.id for t in tracks] == ["sapphire-358"] and stale is False
    await catalog.cache.delete("trending:english:12")  # the fresh copy expires
    provider.delay = 0.5
    tracks, stale = await catalog.trending_state("English", 12, timeout=0.05)
    assert [t.id for t in tracks] == ["sapphire-358"] and stale is True
    with pytest.raises(ProviderUnavailable):  # nothing to fall back on
        await catalog.trending_state("Hindi", 12, timeout=0.05)
