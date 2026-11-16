from app.tests.conftest import auth, register

API = "/api/v1"


async def _setup(client):
    h = auth(await register(client))
    pl = (await client.post(f"{API}/playlists", headers=h, json={"name": "Road trip", "description": "vibes"})).json()
    return h, pl["id"]


async def test_create_update_delete(client):
    h, pid = await _setup(client)
    r = await client.put(f"{API}/playlists/{pid}", headers=h, json={"name": "Road trip 2", "is_public": True})
    assert r.json()["name"] == "Road trip 2" and r.json()["is_public"] is True
    lst = (await client.get(f"{API}/library/playlists", headers=h)).json()
    assert len(lst) == 1 and lst[0]["track_count"] == 0
    assert (await client.delete(f"{API}/playlists/{pid}", headers=h)).status_code == 204
    assert (await client.get(f"{API}/library/playlists/{pid}", headers=h)).status_code == 404


async def test_add_songs_dedup_and_failures(client):
    h, pid = await _setup(client)
    r = await client.post(f"{API}/playlists/{pid}/songs", headers=h,
                          json={"song_ids": ["tyler-herro", "tyler-herro-2", "tyler-herro", "missing-song"]})
    body = r.json()
    assert r.status_code == 200
    assert body["added"] == ["tyler-herro", "tyler-herro-2"]
    assert body["failed"] == {"missing-song": "Song not found at provider"}
    assert [e["position"] for e in body["playlist"]["tracks"]] == [0, 1]

    r = await client.post(f"{API}/playlists/{pid}/songs", headers=h, json={"song_ids": ["tyler-herro"]})
    assert r.json()["already_present"] == ["tyler-herro"]
    summary = (await client.get(f"{API}/library/playlists", headers=h)).json()[0]
    assert summary["track_count"] == 2 and len(summary["artwork"]) == 2


async def test_remove_and_reorder_keep_positions_contiguous(client):
    h, pid = await _setup(client)
    ids = ["tyler-herro", "tyler-herro-2", "industry-baby"]
    await client.post(f"{API}/playlists/{pid}/songs", headers=h, json={"song_ids": ids})

    r = await client.put(f"{API}/playlists/{pid}/order", headers=h, json={"song_ids": list(reversed(ids))})
    assert [e["track"]["id"] for e in r.json()["tracks"]] == list(reversed(ids))

    r = await client.delete(f"{API}/playlists/{pid}/songs/tyler-herro-2", headers=h)
    tracks = r.json()["tracks"]
    assert [e["track"]["id"] for e in tracks] == ["industry-baby", "tyler-herro"]
    assert [e["position"] for e in tracks] == [0, 1]

    assert (await client.delete(f"{API}/playlists/{pid}/songs/tyler-herro-2", headers=h)).status_code == 404
    bad = await client.put(f"{API}/playlists/{pid}/order", headers=h, json={"song_ids": ["tyler-herro"]})
    assert bad.status_code == 422


async def test_adding_listed_lite_songs_needs_no_song_lookups(client, fake_gaana):
    # Search rows are lite (no streams, album or duration). Adding all of them to a
    # playlist must reuse the listed metadata, not send one songDetail request per song.
    h, pid = await _setup(client)
    found = (await client.get(f"{API}/search", params={"q": "tum hi ho", "type": "songs", "limit": 20})).json()
    ids = [s["id"] for s in found["songs"]]
    assert len(ids) == 20
    r = await client.post(f"{API}/playlists/{pid}/songs", headers=h, json={"song_ids": ids})
    body = r.json()
    assert body["added"] == ids and body["failed"] == {}
    assert body["playlist"]["tracks"][0]["track"]["title"] == found["songs"][0]["title"]
    assert "/songs/info/" not in fake_gaana.calls
