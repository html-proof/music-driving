from app.tests.conftest import auth, register

API = "/api/v1"


async def test_song_metadata_matches_provider(client):
    r = await client.get(f"{API}/songs/tyler-herro")
    assert r.status_code == 200
    song = r.json()
    assert song["id"] == "tyler-herro"
    assert song["title"] == "Tyler Herro"
    assert song["artists"][0] == {"name": "Jack Harlow", "id": "jack-harlow", "numeric_id": "817522"}
    assert song["album"]["id"] == "tyler-herro"
    assert song["duration"] == 156
    assert song["playable"] is True
    # Artwork must be the album art for this exact album (id in the CDN path).
    assert "4Z9bqo3yQn" in song["artwork"]["large"]
    assert "stream_urls" not in song and "url" not in song  # streams only via /playback/stream


async def test_unknown_song_is_404(client):
    r = await client.get(f"{API}/songs/does-not-exist")
    assert r.status_code == 404


async def test_invalid_seokey_rejected(client):
    r = await client.get(f"{API}/songs/bad%20key!")
    assert r.status_code == 422


async def test_search_aggregates_sections(client):
    r = await client.get(f"{API}/search", params={"q": "Tyler Herro"})
    assert r.status_code == 200
    body = r.json()
    assert [s["id"] for s in body["songs"]] == ["tyler-herro", "tyler-herro-2"]
    assert body["albums"] and body["artists"]
    assert body["errors"] == {}


async def test_search_strips_unsupported_characters(client, fake_gaana):
    r = await client.get(f"{API}/search", params={"q": "tyler   herro!!"})
    assert r.status_code == 200
    assert r.json()["songs"][0]["id"] == "tyler-herro"


async def test_search_reports_provider_outage_per_section(client, fake_gaana):
    fake_gaana.down = True
    r = await client.get(f"{API}/search", params={"q": "something new"})
    assert r.status_code == 200
    assert r.json()["errors"]["songs"] == "Music provider is currently unavailable"


async def test_search_history_saved_for_user(client):
    tokens = await register(client)
    await client.get(f"{API}/search", params={"q": "tyler herro", "save": True}, headers=auth(tokens))
    await client.get(f"{API}/search", params={"q": "Tyler Herro", "save": True}, headers=auth(tokens))
    r = await client.get(f"{API}/library/search-history", headers=auth(tokens))
    assert [e["query"] for e in r.json()] == ["Tyler Herro"]  # de-duplicated, latest wins


async def test_album_artist_playlist(client):
    album = (await client.get(f"{API}/albums/tyler-herro")).json()
    assert album["title"] == "Tyler Herro" and album["tracks"][0]["id"] == "tyler-herro"

    artist = (await client.get(f"{API}/artists/jack-harlow")).json()
    assert artist["name"] == "Jack Harlow" and artist["numeric_id"] == "817522"
    assert artist["top_tracks"] and artist["similar_artists"]
    assert artist["is_followed"] is False

    tracks = (await client.get(f"{API}/artists/817522/tracks", params={"limit": 3})).json()
    assert len(tracks["items"]) == 3 and tracks["has_more"] is True

    playlist = (await client.get(f"{API}/playlists/gaana-dj-hindi-top-50-1")).json()
    assert playlist["title"] == "Hindi Top 50"  # metadata joined from the chart listing
    assert len(playlist["tracks"]) == 3


async def test_trending_new_releases_charts(client):
    trending = (await client.get(f"{API}/trending", params={"language": "English"})).json()
    assert trending and all(t["language"] == "English" for t in trending)
    new = (await client.get(f"{API}/new-releases", params={"language": "english"})).json()
    assert new["language"] == "English" and new["albums"]
    charts = (await client.get(f"{API}/charts")).json()
    assert charts[0]["id"] == "gaana-dj-hindi-top-50-1"


async def test_catalog_responses_are_cached(client, fake_gaana):
    await client.get(f"{API}/albums/tyler-herro")
    await client.get(f"{API}/albums/tyler-herro")
    assert fake_gaana.calls.count("/albums/info/") == 1


async def test_provider_outage_returns_503(client, fake_gaana):
    fake_gaana.down = True
    r = await client.get(f"{API}/albums/tyler-herro")
    assert r.status_code == 503


async def test_home_feed_real_sections(client):
    r = await client.get(f"{API}/home", params={"languages": "English"})
    assert r.status_code == 200
    home = r.json()
    ids = [s["id"] for s in home["sections"]]
    assert ids[0] == "trending_english"
    assert "new_albums" in ids and "charts" in ids
    assert home["greeting"].startswith("Good")


async def test_home_includes_recently_played_for_user(client):
    tokens = await register(client)
    h = auth(tokens)
    r = await client.post(f"{API}/playback/complete", headers=h,
                          json={"song_id": "tyler-herro", "seconds_listened": 150})
    assert r.json() == {"recorded": True}
    home = (await client.get(f"{API}/home", headers=h, params={"languages": "English"})).json()
    assert home["sections"][0]["id"] == "recently_played"
    assert home["sections"][0]["tracks"][0]["id"] == "tyler-herro"
    assert home["greeting"].endswith("Listener")


async def test_health(client):
    assert (await client.get("/health")).json() == {"status": "ok"}
    r = await client.get("/health/ready")
    assert r.status_code == 200, r.text
