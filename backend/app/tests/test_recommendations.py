from app.tests.conftest import auth, register

API = "/api/v1"


async def test_no_signals_means_no_fake_personalisation(client):
    h = auth(await register(client))
    r = (await client.get(f"{API}/recommendations", headers=h)).json()
    assert r["personalized"] is False and r["items"] == []
    assert "Play, like or follow" in r["message"]


async def test_recommendations_from_history_and_likes(client):
    h = auth(await register(client))
    await client.post(f"{API}/playback/complete", headers=h, json={"song_id": "tyler-herro", "seconds_listened": 156})
    await client.post(f"{API}/library/liked/tyler-herro", headers=h)
    r = (await client.get(f"{API}/recommendations", headers=h)).json()
    assert r["personalized"] is True
    assert "Jack Harlow" in r["based_on"]["artists"]
    ids = [i["track"]["id"] for i in r["items"]]
    assert ids, r
    assert "tyler-herro" not in ids  # just played and liked -> excluded
    assert len(ids) == len(set(ids))
    assert all(i["reason"] for i in r["items"])
    assert any(i["reason"] == "Because you listen to Jack Harlow" for i in r["items"])
