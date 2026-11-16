"""Live checks against a running GaanaPy (and the real Gaana CDN).

    LIVE_PROVIDER=1 GAANAPY_BASE_URL=http://localhost:8001 pytest -m live
"""

import os

import httpx
import pytest

from app.config import Settings
from app.integrations.gaanapy.client import GaanaPyClient
from app.integrations.gaanapy.provider import GaanaProvider
from app.main import make_stream_probe
from app.schemas.music import AudioQuality
from app.services.cache import MemoryCache
from app.services.catalog_service import CatalogService

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(os.getenv("LIVE_PROVIDER") != "1", reason="set LIVE_PROVIDER=1 to hit the real provider"),
]


@pytest.fixture
async def catalog():
    settings = Settings(environment="test")
    client = GaanaPyClient(os.getenv("GAANAPY_BASE_URL", "http://localhost:8001"), retries=1)
    probe_http = httpx.AsyncClient(follow_redirects=True)
    yield CatalogService(GaanaProvider(client), MemoryCache(), settings, make_stream_probe(probe_http))
    await client.close()
    await probe_http.aclose()


async def test_live_song_and_stream(catalog):
    song = await catalog.song("tyler-herro")
    assert song.title == "Tyler Herro" and song.artists[0].name == "Jack Harlow"
    stream = await catalog.stream("tyler-herro", AudioQuality.high)
    assert stream.url.startswith("https://") and stream.expires_at is not None
    async with httpx.AsyncClient() as http:
        master = await http.get(stream.url)
    assert master.status_code == 200 and master.text.startswith("#EXTM3U")


async def test_live_search(catalog):
    results = await catalog.search("tyler herro", 5)
    assert any(s.id == "tyler-herro" for s in results.songs), results


async def test_live_trending_and_charts(catalog):
    assert await catalog.trending("Hindi", 5)
    charts = await catalog.charts(5)
    assert charts
    playlist = await catalog.playlist(charts[0].id)
    assert playlist.tracks and playlist.title == charts[0].title
