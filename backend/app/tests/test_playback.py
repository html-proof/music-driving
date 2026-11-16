from datetime import UTC, datetime

from app.tests.conftest import auth, register

API = "/api/v1"


async def test_stream_url_is_fresh_and_verified(client, app):
    h = auth(await register(client))
    r = await client.get(f"{API}/playback/stream/tyler-herro", headers=h, params={"quality": "very_high"})
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["quality"] == "very_high" and s["bitrate_kbps"] == 320
    assert "/320.mp4.master.m3u8" in s["url"]
    assert datetime.fromisoformat(s["expires_at"]) > datetime.now(UTC)
    assert s["available_qualities"] == ["very_high", "high", "medium", "low"]


async def test_stream_never_claims_unverified_quality(client):
    h = auth(await register(client))
    # The test probe reports the 16 kbps rendition as missing, so 'low' must fall back.
    s = (await client.get(f"{API}/playback/stream/tyler-herro", headers=h, params={"quality": "low"})).json()
    assert s["requested_quality"] == "low"
    assert s["quality"] == "medium" and "/64.mp4" in s["url"]


async def test_stream_uses_user_preferred_quality(client):
    h = auth(await register(client))
    await client.patch(f"{API}/users/me/preferences", headers=h, json={"audio_quality": "medium"})
    s = (await client.get(f"{API}/playback/stream/tyler-herro", headers=h)).json()
    assert s["quality"] == "medium"


async def test_unknown_song_stream_says_unavailable_not_search_error(client):
    h = auth(await register(client))
    r = await client.get(f"{API}/playback/stream/missing-song", headers=h)
    assert r.status_code == 404
    assert r.json()["detail"] == "This song isn't available to stream"


async def test_stream_requires_auth(client):
    assert (await client.get(f"{API}/playback/stream/tyler-herro")).status_code == 401


async def test_session_progress_queue(client):
    h = auth(await register(client))
    queue = ["tyler-herro", "missing-song", "tyler-herro-2"]
    r = await client.post(f"{API}/playback/session", headers=h,
                          json={"queue": queue, "current_index": 2, "shuffle": True, "repeat_mode": "all",
                                "context": "album:tyler-herro"})
    assert r.status_code == 200
    sid = r.json()["id"]

    r = await client.post(f"{API}/playback/progress", headers=h,
                          json={"session_id": sid, "song_id": "tyler-herro-2", "position_seconds": 42.5})
    assert r.json()["position_seconds"] == 42.5

    q = (await client.get(f"{API}/playback/queue", headers=h)).json()
    assert [t["id"] for t in q["tracks"]] == ["tyler-herro", "tyler-herro-2"]
    assert q["unavailable"] == ["missing-song"]
    assert q["current_index"] == 1  # index re-mapped after dropping the unavailable song
    assert q["shuffle"] is True and q["repeat_mode"] == "all"

    # Updating again replaces the same session rather than creating a new one.
    r2 = await client.post(f"{API}/playback/session", headers=h, json={"queue": ["tyler-herro"], "current_index": 0})
    assert r2.json()["id"] == sid


async def test_session_index_validation(client):
    h = auth(await register(client))
    r = await client.post(f"{API}/playback/session", headers=h, json={"queue": ["a-b"], "current_index": 3})
    assert r.status_code == 422


async def test_lyrics_synced_from_lrclib(client):
    r = await client.get(f"{API}/lyrics/tyler-herro")
    assert r.status_code == 200
    ly = r.json()
    assert ly["available"] and ly["synced"]
    assert [(line["time_ms"], line["text"]) for line in ly["lines"]] == [
        (1500, "Line one"), (4250, "Line two"), (4250, "Repeat"), (10000, "Repeat")
    ]


async def test_lyrics_unavailable_state(client):
    ly = (await client.get(f"{API}/lyrics/industry-baby")).json()
    assert ly["available"] is False and ly["synced"] is False and ly["lines"] == []
