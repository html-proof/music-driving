"""Test setup.

* The music provider is the real GaanaPy client + normaliser, wired to an httpx
  MockTransport that replays responses recorded from a live GaanaPy instance
  (app/tests/fixtures). Stream-token expiry is rewritten to "now + 4h" on replay.
* fixtures/gaana_raw holds raw Gaana search responses recorded live; `lite_song_rows`
  turns them into GaanaPy's lite search rows exactly as the GaanaPy contract (A3)
  specifies, so search / list tests run on real catalogue data.
* Database: SQLite by default; set TEST_DATABASE_URL to run against PostgreSQL.
* Live provider tests (tests/test_live_provider.py) only run with LIVE_PROVIDER=1.
"""

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

import httpx
import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret")
os.environ["ENVIRONMENT"] = "test"
os.environ["REDIS_URL"] = ""
_tmpdir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{_tmpdir}/test.db"

from app.config import Settings  # noqa: E402
from app.database import Base, create_engine_from_settings  # noqa: E402
from app.integrations.gaanapy.client import GaanaPyClient  # noqa: E402
from app.integrations.gaanapy.provider import GaanaProvider  # noqa: E402
from app.main import create_app  # noqa: E402
from app.services.cache import MemoryCache  # noqa: E402
from app.services.lyrics_service import LyricsService  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

RAW = FIXTURES / "gaana_raw"
_SIZE_TOKEN = re.compile(r"size_[sml](?=[_.])")

ROUTES = {
    ("/songs/search/", "tyler herro"): "songs_search_tyler_herro",
    ("/songs/info/", "tyler-herro"): "songs_info_tyler_herro",
    ("/albums/info/", "tyler-herro"): "albums_info_tyler_herro",
    ("/albums/search/", "tyler herro"): "albums_search",
    ("/artists/search/", "tyler herro"): "artists_search_arijit",
    ("/artists/info/", "jack-harlow"): "artists_info_jack_harlow",
    ("/artists/tracks/", "817522"): "artists_tracks_817522",
    ("/artists/similar/", "817522"): "artists_similar_817522",
    ("/trending", "English"): "trending_english",
    ("/newreleases", "English"): "newreleases_english",
    ("/charts", None): "charts",
    ("/playlists/info/", "gaana-dj-hindi-top-50-1"): "playlist_hindi_top_50",
}


# GaanaPy lite rows built from a recorded raw Gaana search: (path, key) -> (raw file, language or None).
LITE_ROUTES = {
    ("/songs/search/", "tum hi ho"): ("search_tum_hi_ho", None),
    ("/songs/search/", "malare"): ("search_malare", None),
    ("/songs/search/", "the weeknd"): ("search_the_weeknd", None),
    ("/trending", "Hindi"): ("search_tum_hi_ho", "Hindi"),
    ("/trending", "Tamil"): ("search_malare", "Tamil"),
}
# One-row artist search by name (Home's popular artists).
ROUTES[("/artists/search/", "arijit singh")] = "artists_search_arijit"
# GaanaPy's error bodies (contract A1).
FAILURES = {
    "blocked": (503, {"error": "blocked", "upstream_status": 403, "retry_after": 120}),
    "unavailable": (502, {"error": "upstream_unavailable", "detail": "ReadTimeout"}),
    "internal": (500, {"error": "internal", "detail": "KeyError"}),
}


def _artwork(aw: str) -> dict:
    return {"urls": {f"{size}_artwork": _SIZE_TOKEN.sub(f"size_{size[0]}", aw) if aw else ""
                     for size in ("small", "medium", "large")}}


def lite_song_row(gd: dict) -> dict:
    """A GaanaPy lite song row, built from one raw Gaana search item (contract A3)."""
    names = gd.get("sti") or (gd.get("alist") or "").strip("[]")
    lang = gd.get("language") or ((gd.get("lang") or [""])[0])
    return {
        "seokey": gd["seo"], "track_id": str(gd["id"]), "title": gd["ti"],
        "artists": ", ".join(n.strip() for n in names.split(",") if n.strip()),
        "artist_seokeys": "", "artist_ids": "", "album": "", "album_seokey": "", "album_id": "",
        "duration": "", "language": lang, "images": _artwork(gd.get("aw") or ""),
        "stream_urls": {"urls": {}}, "lite": True,
    }


def lite_song_rows(name: str, language: str | None = None) -> list[dict]:
    raw = json.loads((RAW / f"{name}.json").read_text(encoding="utf-8"))
    items = [gd for group in raw["gr"] if group.get("ty") == "Track" for gd in group["gd"]]
    rows = [lite_song_row(gd) for gd in items]
    return [r for r in rows if language is None or r["language"] == language]


def _load(name: str):
    raw = (FIXTURES / f"{name}.json").read_text()
    raw = re.sub(r"exp=\d+", f"exp={int(time.time()) + 4 * 3600}", raw)
    return json.loads(raw)


def _all_tracks() -> dict[str, dict]:
    """Every track found in any fixture, keyed by seokey (serves /songs/info/ for them)."""
    found: dict[str, dict] = {}

    def walk(o):
        if isinstance(o, dict):
            if o.get("seokey") and "stream_urls" in o:
                found.setdefault(o["seokey"], o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for f in FIXTURES.glob("*.json"):
        walk(_load(f.stem))
    return found


class FakeGaanaPy:
    """Replays recorded GaanaPy responses; counts calls so tests can assert caching."""

    def __init__(self):
        self.calls: list[str] = []
        self.requests: list[tuple[str, dict]] = []  # (path, query params) of every call
        # Every request fails like this ("blocked", "unavailable", "internal"; see FAILURES).
        self.failure: str | None = None
        # Only matching requests fail: (path, key) -> FAILURES name, or an HTTP status.
        self.fail: dict[tuple[str, str], str | int] = {}
        self.tracks = _all_tracks()

    @property
    def down(self) -> bool:
        """Gaana is blocking us (GaanaPy answers 503 "blocked")."""
        return self.failure == "blocked"

    @down.setter
    def down(self, value: bool) -> None:
        self.failure = "blocked" if value else None

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        p = request.url.params
        self.calls.append(path)
        self.requests.append((path, dict(p)))
        if self.failure:
            status, body = FAILURES[self.failure]
            return httpx.Response(status, json=body)
        if path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        key = p.get("query") or p.get("seokey") or p.get("artist_id") or p.get("album_id") or p.get("language")
        if p.get("query"):
            key = key.lower()  # Gaana search is case-insensitive
        failure = self.fail.get((path, key))
        if failure is not None:
            status, body = FAILURES[failure] if isinstance(failure, str) else (failure, {"detail": "rejected"})
            return httpx.Response(status, json=body)
        rows = None
        if (path, key) in LITE_ROUTES:
            rows = lite_song_rows(*LITE_ROUTES[(path, key)])
        elif name := ROUTES.get((path, key)):
            rows = _load(name)
        if rows is not None and path.endswith("/search/"):
            # GaanaPy slices search pages out of Gaana's first result page (contract A2).
            limit, page = int(p.get("limit", 10)), int(p.get("page", 1))
            rows = rows[(page - 1) * limit: page * limit]
            if not rows:
                return httpx.Response(404, json={"detail": "Unable to find any results!"})
        elif rows is not None and path == "/trending" and isinstance(rows, list):
            rows = rows[: int(p.get("limit", len(rows)))]
        if rows is not None:
            return httpx.Response(200, json=rows)
        if path == "/songs/info/" and key in self.tracks:
            return httpx.Response(200, json=[self.tracks[key]])
        return httpx.Response(404, json={"detail": "Unable to find any results!"})


def lrclib_handler(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/api/get" and request.url.params.get("track_name") == "Tyler Herro":
        return httpx.Response(200, json={
            "id": 123, "trackName": "Tyler Herro", "artistName": "Jack Harlow", "duration": 156,
            "instrumental": False, "plainLyrics": "Line one\nLine two",
            "syncedLyrics": "[00:01.50] Line one\n[00:04.25] Line two\n[00:04.25][00:10.00] Repeat",
        })
    if request.url.path == "/api/search":
        return httpx.Response(200, json=[])
    return httpx.Response(404, json={"message": "not found"})


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def event_loop_policy():
    # psycopg async (PostgreSQL test runs) needs a selector loop on Windows.
    import asyncio

    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
def fake_gaana() -> FakeGaanaPy:
    return FakeGaanaPy()


@pytest.fixture
def settings() -> Settings:
    return Settings(environment="test", redis_url="", verify_stream_quality=True)


@pytest.fixture
async def app(fake_gaana, settings):
    engine = create_engine_from_settings(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()

    client = GaanaPyClient("http://gaanapy.test", retries=0, transport=httpx.MockTransport(fake_gaana.handler))
    lyrics = LyricsService("http://lrclib.test", "test", MemoryCache(), transport=httpx.MockTransport(lrclib_handler))
    probe_calls: list[str] = []

    async def probe(url: str) -> bool:
        probe_calls.append(url)
        return "/16.mp4" not in url  # pretend the derived 16 kbps rendition does not exist

    application = create_app(settings, provider=GaanaProvider(client), lyrics=lyrics, stream_probe=probe)
    application.state_probe_calls = probe_calls
    async with application.router.lifespan_context(application):
        yield application
    await client.close()
    await lyrics.close()


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


def device_creds(who: str = "default") -> dict:
    """Deterministic test credentials for a device called `who`."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", who)
    return {"device_id": f"test-device-{slug}", "device_secret": f"secret-{slug}-" + "x" * 40, "platform": "android"}


async def register(client: httpx.AsyncClient, who: str = "default"):
    """Create a device account (first launch of the app) and return its tokens."""
    r = await client.post("/api/v1/auth/device", json=device_creds(who))
    assert r.status_code == 201, r.text
    return r.json()


def auth(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}
