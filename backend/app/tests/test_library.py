from app.tests.conftest import auth, register

API = "/api/v1"


async def test_like_unlike_and_status(client):
    h = auth(await register(client))
    assert (await client.post(f"{API}/library/liked/tyler-herro", headers=h)).json()["liked"] is True
    assert (await client.post(f"{API}/library/liked/tyler-herro", headers=h)).status_code == 200  # idempotent
    page = (await client.get(f"{API}/library/liked", headers=h)).json()
    assert page["total"] == 1 and page["items"][0]["track"]["title"] == "Tyler Herro"
    status = (await client.get(f"{API}/library/liked/status", headers=h,
                               params={"ids": "tyler-herro,tyler-herro-2"})).json()
    assert status == {"tyler-herro": True, "tyler-herro-2": False}
    await client.delete(f"{API}/library/liked/tyler-herro", headers=h)
    assert (await client.get(f"{API}/library/liked", headers=h)).json()["total"] == 0


async def test_like_unknown_song_404(client):
    h = auth(await register(client))
    assert (await client.post(f"{API}/library/liked/no-such-song", headers=h)).status_code == 404


async def test_follow_artist(client):
    h = auth(await register(client))
    assert (await client.post(f"{API}/library/followed-artists/jack-harlow", headers=h)).status_code == 204
    followed = (await client.get(f"{API}/library/followed-artists", headers=h)).json()
    assert followed[0]["artist"]["name"] == "Jack Harlow"
    assert (await client.get(f"{API}/artists/jack-harlow", headers=h)).json()["is_followed"] is True
    await client.delete(f"{API}/library/followed-artists/jack-harlow", headers=h)
    assert (await client.get(f"{API}/library/followed-artists", headers=h)).json() == []


async def test_user_data_isolation(client):
    alice = auth(await register(client, "alice-phone"))
    bob = auth(await register(client, "bob-phone"))
    await client.post(f"{API}/library/liked/tyler-herro", headers=alice)
    await client.post(f"{API}/playback/complete", headers=alice, json={"song_id": "tyler-herro", "seconds_listened": 60})
    pl = (await client.post(f"{API}/playlists", headers=alice, json={"name": "Alice only"})).json()

    assert (await client.get(f"{API}/library/liked", headers=bob)).json()["total"] == 0
    assert (await client.get(f"{API}/library/history", headers=bob)).json()["items"] == []
    assert (await client.get(f"{API}/library/playlists", headers=bob)).json() == []
    assert (await client.get(f"{API}/library/playlists/{pl['id']}", headers=bob)).status_code == 404
    assert (await client.put(f"{API}/playlists/{pl['id']}", headers=bob, json={"name": "hacked"})).status_code == 404
    assert (await client.delete(f"{API}/playlists/{pl['id']}", headers=bob)).status_code == 404
    r = await client.post(f"{API}/playlists/{pl['id']}/songs", headers=bob, json={"song_ids": ["tyler-herro"]})
    assert r.status_code == 404


async def test_history_and_recently_played(client):
    h = auth(await register(client))
    for sid in ["tyler-herro", "tyler-herro-2", "tyler-herro"]:
        await client.post(f"{API}/playback/complete", headers=h, json={"song_id": sid, "seconds_listened": 30})
    # Too short to count as a play.
    r = await client.post(f"{API}/playback/complete", headers=h, json={"song_id": "tyler-herro-2", "seconds_listened": 2})
    assert r.json() == {"recorded": False}
    hist = (await client.get(f"{API}/library/history", headers=h)).json()
    assert len(hist["items"]) == 3
    recent = (await client.get(f"{API}/library/recently-played", headers=h)).json()
    assert [t["id"] for t in recent] == ["tyler-herro", "tyler-herro-2"]
    await client.delete(f"{API}/library/history", headers=h)
    assert (await client.get(f"{API}/library/history", headers=h)).json()["items"] == []
