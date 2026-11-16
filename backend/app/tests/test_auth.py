from app.tests.conftest import auth, device_creds, register

API = "/api/v1"


async def test_first_launch_creates_account(client):
    tokens = await register(client)
    assert tokens["created"] is True and tokens["token_type"] == "bearer" and tokens["expires_in"] > 0
    me = (await client.get(f"{API}/users/me", headers=auth(tokens))).json()
    assert me["display_name"] == "Listener"
    assert me["preferences"]["languages"] == ["English", "Hindi"]
    assert "email" not in me
    devices = (await client.get(f"{API}/users/me/devices", headers=auth(tokens))).json()
    assert devices[0]["installation_id"] == device_creds()["device_id"]


async def test_same_device_resumes_same_account(client):
    first = await register(client)
    me1 = (await client.get(f"{API}/users/me", headers=auth(first))).json()
    r = await client.post(f"{API}/auth/device", json=device_creds())
    assert r.status_code == 200 and r.json()["created"] is False
    me2 = (await client.get(f"{API}/users/me", headers=auth(r.json()))).json()
    assert me1["id"] == me2["id"]


async def test_wrong_secret_for_existing_device_rejected(client):
    await register(client)
    creds = device_creds() | {"device_secret": "y" * 48}
    r = await client.post(f"{API}/auth/device", json=creds)
    assert r.status_code == 401


async def test_weak_device_credentials_rejected(client):
    r = await client.post(f"{API}/auth/device", json={"device_id": "short", "device_secret": "tiny"})
    assert r.status_code == 422


async def test_email_password_auth_removed(client):
    assert (await client.post(f"{API}/auth/login", json={})).status_code == 404
    assert (await client.post(f"{API}/auth/register", json={})).status_code == 404


async def test_protected_routes_require_token(client):
    assert (await client.get(f"{API}/users/me")).status_code == 401
    assert (await client.get(f"{API}/users/me", headers={"Authorization": "Bearer garbage"})).status_code == 401


async def test_refresh_rotation_and_reuse_detection(client):
    tokens = await register(client)
    r = await client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert r.status_code == 200
    rotated = r.json()
    assert rotated["refresh_token"] != tokens["refresh_token"]
    # Re-using the old token is treated as theft: it fails and revokes the rotated one too.
    assert (await client.post(f"{API}/auth/refresh", json={"refresh_token": tokens["refresh_token"]})).status_code == 401
    assert (await client.post(f"{API}/auth/refresh", json={"refresh_token": rotated["refresh_token"]})).status_code == 401
    # The device can always get back in with its secret.
    r = await client.post(f"{API}/auth/device", json=device_creds())
    assert r.status_code == 200


async def test_profile_preferences_devices(client):
    h = auth(await register(client))
    r = await client.patch(f"{API}/users/me", headers=h, json={"display_name": "New Name", "country": "in"})
    assert r.json()["display_name"] == "New Name" and r.json()["country"] == "IN"
    r = await client.patch(f"{API}/users/me/preferences", headers=h,
                           json={"languages": ["punjabi", "English"], "audio_quality": "very_high"})
    assert r.json() == {"languages": ["Punjabi", "English"], "audio_quality": "very_high", "allow_explicit": True}
    assert (await client.patch(f"{API}/users/me/preferences", headers=h, json={"audio_quality": "ultra"})).status_code == 422
    r = await client.patch(f"{API}/users/me/notifications", headers=h, json={"new_releases": False})
    assert r.json()["new_releases"] is False
    r = await client.put(f"{API}/users/me/devices", headers=h,
                         json={"installation_id": device_creds()["device_id"], "platform": "android", "push_token": "fcm"})
    assert r.status_code == 200 and r.json()["has_push_token"] is True
    assert len((await client.get(f"{API}/users/me/devices", headers=h)).json()) == 1


async def test_delete_my_data_then_start_fresh(client):
    tokens = await register(client)
    h = auth(tokens)
    await client.post(f"{API}/playlists", headers=h, json={"name": "Mine"})
    assert (await client.delete(f"{API}/users/me", headers=h)).status_code == 204
    assert (await client.get(f"{API}/users/me", headers=h)).status_code == 401
    # Same device registers again as a brand-new, empty account.
    fresh = await client.post(f"{API}/auth/device", json=device_creds())
    assert fresh.status_code == 201
    assert (await client.get(f"{API}/library/playlists", headers=auth(fresh.json()))).json() == []
