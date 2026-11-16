"""Local fix: route validation and the error bodies callers rely on.

Offline: the GaanaPy object behind the routes is a fake. Requests go straight to the
ASGI app (starlette's TestClient needs an HTTP client package this venv doesn't have).
"""

import asyncio
import json
from urllib.parse import urlencode

import pytest

import app as app_module
from api.errors import BlockedError, UpstreamUnavailable


class FakeGaana:
    def __init__(self, outcome=None):
        self.outcome = outcome
        self.calls = []

    def _answer(self, name, *args):
        self.calls.append((name, args))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome if self.outcome is not None else [{"seokey": "x"}]

    async def search_songs(self, *args):
        return self._answer("search_songs", *args)

    async def search_albums(self, *args):
        return self._answer("search_albums", *args)

    async def search_artists(self, *args):
        return self._answer("search_artists", *args)

    async def get_playlist_info(self, *args):
        return self._answer("get_playlist_info", *args)

    async def get_track_info(self, *args, **kwargs):
        return self._answer("get_track_info", *args)


class Response:
    def __init__(self, status_code, headers, body):
        self.status_code = status_code
        self.headers = headers
        self.body = body

    def json(self):
        return json.loads(self.body)


class AsgiClient:
    """Minimal GET-only ASGI client (no lifespan: the fake is installed directly)."""

    def __init__(self, asgi_app):
        self.app = asgi_app

    def get(self, path, params=None):
        return asyncio.run(self._get(path, params or {}))

    async def _get(self, path, params):
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
            "scheme": "http", "path": path, "raw_path": path.encode(), "root_path": "",
            "query_string": urlencode(params).encode(), "headers": [(b"host", b"test")],
            "client": ("test", 1), "server": ("test", 80),
        }
        sent = {"status": None, "headers": {}, "body": b""}

        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            if message["type"] == "http.response.start":
                sent["status"] = message["status"]
                sent["headers"] = {k.decode().lower(): v.decode() for k, v in message["headers"]}
            elif message["type"] == "http.response.body":
                sent["body"] += message.get("body", b"")

        try:
            await self.app(scope, receive, send)
        except Exception:
            # Starlette re-raises unhandled errors after the 500 handler has answered.
            if sent["status"] is None:
                raise
        return Response(sent["status"], {k.title(): v for k, v in sent["headers"].items()}, sent["body"])


@pytest.fixture
def client(monkeypatch):
    def make(outcome=None):
        fake = FakeGaana(outcome)
        monkeypatch.setattr(app_module, "gaanapy", fake)
        return AsgiClient(app_module.app), fake
    return make


@pytest.mark.parametrize("query", [
    "മലരേ", "கொலவெறி", "तुम ही हो", "Beyoncé", "P!nk", "Simon & Garfunkel", "AC/DC (Live)?",
])
@pytest.mark.parametrize("route", ["/songs/search/", "/albums/search/", "/artists/search/"])
def test_search_accepts_any_script_and_punctuation(client, route, query):
    http, fake = client()

    response = http.get(route, params={"query": query})

    assert response.status_code == 200
    assert fake.calls[0][1] == (query, 10, 1)


def test_search_query_is_cleaned(client):
    http, fake = client()

    response = http.get("/songs/search/", params={"query": "  Tum\tHi\x00  Ho\n", "limit": 5, "page": 3})

    assert response.status_code == 200
    assert fake.calls[0][1] == ("Tum Hi Ho", 5, 3)


@pytest.mark.parametrize("params", [
    {"query": "   \t\n"},
    {"query": ""},
    {"query": "x" * 201},
    {"query": "ok", "page": 0},
    {"query": "ok", "page": 21},
    {"query": "ok", "limit": 101},
])
def test_search_rejects_invalid_input(client, params):
    http, fake = client()

    assert http.get("/songs/search/", params=params).status_code == 422
    assert fake.calls == []


def test_block_is_503_with_retry_after(client):
    http, _ = client(BlockedError(403, 120))

    response = http.get("/songs/search/", params={"query": "Tum Hi Ho"})

    assert response.status_code == 503
    assert response.json() == {"error": "blocked", "upstream_status": 403, "retry_after": 120}
    assert response.headers["Retry-After"] == "120"


def test_outage_is_502(client):
    http, _ = client(UpstreamUnavailable("Gaana unreachable: ServerTimeoutError"))

    response = http.get("/songs/search/", params={"query": "Tum Hi Ho"})

    assert response.status_code == 502
    assert response.json() == {"error": "upstream_unavailable", "detail": "Gaana unreachable: ServerTimeoutError"}


def test_bug_is_500_not_an_upstream_error(client):
    http, _ = client(AttributeError("'NoneType' object has no attribute 'replace'"))

    response = http.get("/songs/search/", params={"query": "Tum Hi Ho"})

    assert response.status_code == 500
    assert response.json() == {"error": "internal", "detail": "AttributeError"}


def test_no_results_is_still_404(client):
    http, _ = client({"error": "Unable to find any results!"})

    response = http.get("/songs/search/", params={"query": "zzzz"})

    assert response.status_code == 404
    assert response.json() == {"detail": "Unable to find any results!"}


def test_playlist_limit_defaults_to_50(client):
    http, fake = client()

    assert http.get("/playlists/info/", params={"seokey": "gaana-dj-hindi-top-50-1"}).status_code == 200
    assert http.get("/playlists/info/", params={"seokey": "top-50", "limit": 5}).status_code == 200
    assert [c[1] for c in fake.calls] == [("gaana-dj-hindi-top-50-1", 50), ("top-50", 5)]


def test_mixed_case_seokeys_from_search_can_be_looked_up(client):
    http, fake = client()

    assert http.get("/songs/info/", params={"seokey": "tum-hi-ho-MWQM71XEWq"}).status_code == 200
    assert fake.calls[0][1] == (["tum-hi-ho-MWQM71XEWq"],)
