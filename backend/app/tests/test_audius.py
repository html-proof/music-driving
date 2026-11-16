"""Audius provider: real client + normaliser + provider, replaying responses recorded from
the public Audius API (fixtures/audius), wired into the full app."""

import copy
import json
from pathlib import Path

import httpx
import pytest

from app.database import Base, create_engine_from_settings
from app.integrations.audius.client import AudiusClient
from app.integrations.audius.provider import AudiusProvider, genre_for
from app.main import create_app
from app.tests.conftest import auth, register

API = "/api/v1"
BASE = "http://audius.test/v1"
FIX = Path(__file__).parent / "fixtures" / "audius"
META = json.loads((FIX / "_meta.json").read_text(encoding="utf-8"))
TRACK_ID, OWNER, PLAYLIST = META["first_track_id"], META["owner_id"], META["playlist_id"]
GATED = "gatedTrack1"


def _load(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


class FakeAudius:
    def __init__(self):
        self.calls: list[httpx.Request] = []
        self.tracks: dict[str, dict] = {}
        for f in FIX.glob("*.json"):
            if f.stem == "_meta":
                continue
            data = _load(f.stem).get("data")
            for row in data if isinstance(data, list) else [data]:
                if isinstance(row, dict) and "is_streamable" in row:  # track records only
                    self.tracks.setdefault(row["id"], row)
        gated = copy.deepcopy(self.tracks[TRACK_ID])
        gated.update(id=GATED, is_stream_gated=True)
        self.tracks[GATED] = gated
        self.routes = {
            "/tracks/trending": "trending", "/tracks/trending/underground": "underground",
            "/tracks/search": "search_tracks", "/users/search": "search_users",
            "/playlists/search": "search_playlists", "/playlists/trending": "trending_playlists",
            "/playlists/top": "top_albums", f"/users/{OWNER}": "user", f"/users/{OWNER}/tracks": "user_tracks",
            f"/users/{OWNER}/related": "related_users", f"/users/{OWNER}/albums": "top_albums",
            f"/playlists/{PLAYLIST}": "playlist", f"/playlists/{PLAYLIST}/tracks": "playlist_tracks",
        }

    def paths(self) -> list[str]:
        return [r.url.path.removeprefix("/v1") for r in self.calls]

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        assert request.url.params.get("app_name") == "Melodia"
        path = request.url.path.removeprefix("/v1")
        if path in self.routes:
            return httpx.Response(200, json=_load(self.routes[path]))
        if path.startswith("/tracks/") and path.count("/") == 2 and path.split("/")[2] in self.tracks:
            return httpx.Response(200, json={"data": self.tracks[path.split("/")[2]]})
        return httpx.Response(404, json={"error": "not found"})


@pytest.fixture
def fake_audius() -> FakeAudius:
    return FakeAudius()


@pytest.fixture
async def audius_client(fake_audius, settings):
    engine = create_engine_from_settings(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    probes: list[str] = []

    async def probe(url: str) -> bool:
        probes.append(url)
        return False  # an HLS check would reject an MP3: it must never run for Audius

    client = AudiusClient(BASE, "Melodia", retries=0, transport=httpx.MockTransport(fake_audius.handler))
    application = create_app(settings, provider=AudiusProvider(client), stream_probe=probe)
    async with application.router.lifespan_context(application):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test") as c:
            c.probes = probes
            yield c
    await client.close()


def test_genre_matching():
    assert genre_for("Jazz") == "Jazz"
    assert genre_for("hip hop rap") == "Hip-Hop/Rap"
    assert genre_for("English") is None
    assert genre_for(None) is None


async def test_home_uses_one_all_genre_feed_for_languages(audius_client, fake_audius):
    r = await audius_client.get(f"{API}/home", params={"languages": "English,Hindi"})
    assert r.status_code == 200, r.text
    feed = r.json()
    titles = [s["title"] for s in feed["sections"]]
    assert titles.count("Trending now") == 1 and not any(t.startswith("Popular in") for t in titles)
    assert {"Top albums", "Fresh & underground", "Trending playlists"} <= set(titles)
    assert feed["languages"] == ["English", "Hindi"]
    trending_calls = [c for c in fake_audius.calls if c.url.path == "/v1/tracks/trending"]
    assert trending_calls and all("genre" not in c.url.params for c in trending_calls)
    first = feed["sections"][0]
    assert first["subtitle"] is None and first["tracks"][0]["id"] == TRACK_ID


async def test_home_filters_by_a_language_that_names_a_genre(audius_client, fake_audius):
    feed = (await audius_client.get(f"{API}/home", params={"languages": "Jazz,English"})).json()
    assert feed["sections"][0]["id"] == "trending_jazz"
    genres = {c.url.params.get("genre") for c in fake_audius.calls if c.url.path == "/v1/tracks/trending"}
    assert genres == {"Jazz"}


async def test_stream_is_a_progressive_mp3_without_hls_check(audius_client, fake_audius):
    h = auth(await register(audius_client, "audius-stream"))
    assert (await audius_client.get(f"{API}/trending")).status_code == 200
    before = len(fake_audius.calls)
    r = await audius_client.get(f"{API}/playback/stream/{TRACK_ID}", headers=h, params={"quality": "very_high"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["format"] == "mp3"
    assert s["url"] == f"{BASE}/tracks/{TRACK_ID}/stream?app_name=Melodia"
    assert s["quality"] == "high" and s["available_qualities"] == ["high"]
    assert s["expires_at"] is None
    assert audius_client.probes == []
    assert len(fake_audius.calls) == before  # listed song: no second /tracks/{id} lookup


async def test_gated_track_is_not_playable(audius_client):
    h = auth(await register(audius_client, "audius-gated"))
    song = (await audius_client.get(f"{API}/songs/{GATED}")).json()
    assert song["playable"] is False
    assert (await audius_client.get(f"{API}/playback/stream/{GATED}", headers=h)).status_code == 404


async def test_search_uses_audius_playlist_search(audius_client, fake_audius):
    r = (await audius_client.get(f"{API}/search", params={"q": "chill", "limit": 4})).json()
    assert r["errors"] == {}
    assert r["songs"] and r["artists"] and r["playlists"]
    assert "/playlists/search" in fake_audius.paths()
    assert "/playlists/trending" not in fake_audius.paths()  # no chart-title matching fallback


async def test_hash_ids_work_for_artist_and_playlist_routes(audius_client):
    artist = await audius_client.get(f"{API}/artists/{OWNER}")
    assert artist.status_code == 200, artist.text
    assert artist.json()["top_tracks"] and artist.json()["similar_artists"]
    page = await audius_client.get(f"{API}/artists/{OWNER}/tracks", params={"limit": 2})
    assert page.status_code == 200, page.text
    playlist = await audius_client.get(f"{API}/playlists/{PLAYLIST}")
    assert playlist.status_code == 200, playlist.text
    assert playlist.json()["tracks"]


async def test_library_stores_audius_songs(audius_client):
    h = auth(await register(audius_client, "audius-like"))
    r = await audius_client.post(f"{API}/library/liked/{TRACK_ID}", headers=h)
    assert r.status_code < 300, r.text
    liked = (await audius_client.get(f"{API}/library/liked", headers=h)).json()
    assert [i["track"]["id"] for i in liked["items"]] == [TRACK_ID]
