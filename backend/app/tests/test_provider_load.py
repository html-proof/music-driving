"""How many requests reach Gaana for common app flows.

The backend talks to GaanaPy, and GaanaPy fans out to Gaana: a trending list is one
Gaana request for the list plus one per song, an artist page is two, and so on. These
tests replay real flows against recorded GaanaPy responses, convert each GaanaPy call
into the Gaana requests it causes, and pin upper bounds so the load can't creep back.

Gaana rate-limits and blocks clients that send bursts, so every request saved here is
what keeps the app working. Run with `-s` to print the per-flow table.
"""

import asyncio

import httpx
import pytest

from app.integrations.gaanapy.client import GaanaPyClient
from app.integrations.gaanapy.provider import GaanaProvider
from app.main import create_app
from app.services.cache import MemoryCache
from app.services.lyrics_service import LyricsService
from app.tests.conftest import FakeGaanaPy, auth, lrclib_handler, register

# GaanaPy endpoints that fetch one Gaana detail page per returned record.
_PER_RECORD = {"/trending", "/songs/search/", "/albums/search/", "/artists/search/"}


class CountingGaanaPy(FakeGaanaPy):
    """FakeGaanaPy that also counts the Gaana requests each GaanaPy call would cause."""

    def __init__(self):
        super().__init__()
        self.gaana_requests = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        resp = super().handler(request)
        path = request.url.path
        if path == "/health":
            return resp
        if resp.status_code != 200:
            self.gaana_requests += 1  # the first request was refused / found nothing
            return resp
        body = resp.json()
        if path in _PER_RECORD and isinstance(body, list):
            self.gaana_requests += 1 + len(body)
        elif path == "/newreleases" and isinstance(body, dict):
            self.gaana_requests += 1 + len(body.get("tracks") or []) + len(body.get("albums") or [])
        elif path == "/artists/info/":
            self.gaana_requests += 2  # artist details + top tracks
        else:
            self.gaana_requests += 1
        return resp


def _cooldown_kwargs(settings) -> dict:
    cooldown = getattr(settings, "provider_block_cooldown_seconds", None)
    return {} if cooldown is None else {"block_cooldown_seconds": cooldown}


@pytest.fixture
def gaana() -> CountingGaanaPy:
    return CountingGaanaPy()


@pytest.fixture
async def prod_app(gaana, settings):
    """The app wired like production: production retry count, real cache, real client."""
    from app.database import Base, create_engine_from_settings

    engine = create_engine_from_settings(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    client = GaanaPyClient("http://gaanapy.test", settings.provider_timeout_seconds, settings.provider_retries,
                           transport=httpx.MockTransport(gaana.handler), **_cooldown_kwargs(settings))
    lyrics = LyricsService("http://lrclib.test", "test", MemoryCache(), transport=httpx.MockTransport(lrclib_handler))

    async def probe(url: str) -> bool:
        return True

    application = create_app(settings, provider=GaanaProvider(client), lyrics=lyrics, stream_probe=probe)
    async with application.router.lifespan_context(application):
        yield application
    await client.close()
    await lyrics.close()


@pytest.fixture
async def http(prod_app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=prod_app), base_url="http://test") as c:
        yield c


API = "/api/v1"
REPORT: dict[str, int] = {}


def _measure(gaana: CountingGaanaPy):
    start = gaana.gaana_requests
    return lambda: gaana.gaana_requests - start


async def test_open_home_then_play_and_show_lyrics(http, gaana):
    h = auth(await register(http))
    used = _measure(gaana)
    home = (await http.get(f"{API}/home", params={"languages": "English"}, headers=h)).json()
    REPORT["open Home (nothing cached)"] = home_cost = used()
    trending = next(s for s in home["sections"] if s["id"] == "trending_english")["tracks"]
    song = trending[0]["id"]

    used = _measure(gaana)
    r = await http.get(f"{API}/playback/stream/{song}", params={"quality": "high"}, headers=h)
    assert r.status_code == 200, r.text
    REPORT["play a song from Home"] = play_cost = used()

    used = _measure(gaana)
    r = await http.get(f"{API}/lyrics/{song}", headers=h)
    assert r.status_code == 200, r.text
    REPORT["open lyrics for that song"] = lyrics_cost = used()

    used = _measure(gaana)
    await http.get(f"{API}/home", params={"languages": "English"}, headers=h)
    REPORT["open Home again (cached)"] = used()

    # Upper bounds. Home still lists real songs, so it costs one list fetch per section,
    # but playing or showing lyrics for a song the app already listed must be free.
    assert home_cost <= 60, home_cost
    assert play_cost == 0, play_cost
    assert lyrics_cost == 0, lyrics_cost


async def test_stream_and_lyrics_requested_together_share_one_lookup(http, gaana):
    h = auth(await register(http))
    used = _measure(gaana)
    stream, lyrics = await asyncio.gather(
        http.get(f"{API}/playback/stream/tyler-herro", params={"quality": "high"}, headers=h),
        http.get(f"{API}/lyrics/tyler-herro", headers=h),
    )
    assert stream.status_code == 200 and lyrics.status_code == 200
    REPORT["stream + lyrics at once (song not cached)"] = cost = used()
    assert cost == 1, cost


async def test_while_gaana_blocks_the_backend_backs_off(http, gaana):
    h = auth(await register(http))
    gaana.down = True
    used = _measure(gaana)
    # The user opens Home, pulls to refresh twice, then taps play on two songs.
    for _ in range(3):
        await http.get(f"{API}/home", params={"languages": "English"}, headers=h)
    for song in ("tyler-herro", "another-song"):
        r = await http.get(f"{API}/playback/stream/{song}", params={"quality": "high"}, headers=h)
        assert r.status_code == 503
        assert r.json()["detail"] == "Music provider is currently unavailable"
    REPORT["blocked: Home x3 + play x2"] = cost = used()
    # Only the first request may reach Gaana; the rest wait out the cooldown locally.
    assert cost <= 1, cost


async def test_home_is_served_from_the_last_good_copy_during_a_block(http, gaana, prod_app):
    h = auth(await register(http))
    first = (await http.get(f"{API}/home", params={"languages": "English"}, headers=h)).json()
    assert any(s["id"] == "trending_english" for s in first["sections"])
    # The normal cache entry expires, then Gaana blocks us.
    cache = prod_app.state.catalog.cache
    for key in [k for k in list(cache._data) if not k.startswith("stale:")]:
        await cache.delete(key)
    gaana.down = True
    second = (await http.get(f"{API}/home", params={"languages": "English"}, headers=h)).json()
    assert any(s["id"] == "trending_english" for s in second["sections"]), second["errors"]


async def test_search(http, gaana):
    h = auth(await register(http))
    used = _measure(gaana)
    r = await http.get(f"{API}/search", params={"q": "tyler herro"}, headers=h)
    assert r.status_code == 200
    REPORT["search (nothing cached)"] = used()
    used = _measure(gaana)
    await http.get(f"{API}/playback/stream/tyler-herro", params={"quality": "high"}, headers=h)
    REPORT["play a search result"] = cost = used()
    assert cost == 0, cost


def test_zz_print_report():
    print("\nGaana requests per flow:")
    for name, n in REPORT.items():
        print(f"  {n:>4}  {name}")
