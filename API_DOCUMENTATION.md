# Melodia API (v1)

Base URL: `https://<your-domain>/api/v1` (local: `http://localhost:8000/api/v1`).
Interactive docs: `GET /docs` · machine-readable schema: [`docs/openapi.json`](docs/openapi.json).

All bodies are JSON. Authenticated endpoints need `Authorization: Bearer <access_token>`.
Errors use `{"detail": "..."}` with these status codes:

| Code | Meaning |
|---|---|
| 401 | Missing/expired/revoked token. Call `/auth/refresh` (or `/auth/device`), then retry once. |
| 404 | Not found (also: someone else's private playlist) |
| 422 | Validation error |
| 429 | Rate limited (`Retry-After` header) |
| 503 | Music provider unavailable (`Retry-After` header). Never reported as "no results". |

## Identifiers

* **Songs, albums, artists, provider playlists** use the provider **seokey** (e.g. `tyler-herro`) as `id`.
* **Artist tracks / similar albums** need the numeric id (`numeric_id` in responses).
* **User playlists** use UUIDs.

## Core objects

```jsonc
// Track
{ "id": "tyler-herro", "track_id": "32408795", "title": "Tyler Herro",
  "artists": [{"name": "Jack Harlow", "id": "jack-harlow", "numeric_id": "817522"}],
  "album": {"id": "tyler-herro", "numeric_id": "3487503", "title": "Tyler Herro"},
  "duration": 156, "language": "English", "genres": ["Hip Hop"], "is_explicit": true,
  "release_date": "2020-10-21",
  "artwork": {"small": "…size_s.jpg", "medium": "…size_m.jpg", "large": "…size_l.jpg"},
  "playable": true, "provider_url": "https://gaana.com/song/tyler-herro" }
```

Tracks never contain stream URLs. Resolve them with `/playback/stream/{song_id}`.

## Health

| Method | Path | Notes |
|---|---|---|
| GET | `/health` | Liveness |
| GET | `/health/ready` | DB, cache and provider checks; 503 when degraded |

## Device sessions (no login)

There are no user names, emails or passwords. On first launch the app generates a random `device_id`
(16+ chars) and a random `device_secret` (32+ chars; the app uses 384 bits), stores them in the platform
keystore, and exchanges them for tokens. Each device has its own anonymous account and library.

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/auth/device` | `{device_id, device_secret, platform?, name?}` | `201` on first call (account created), `200` afterwards: `TokenPair + created` |
| POST | `/auth/refresh` | `{refresh_token}` | `TokenPair` (old refresh token is revoked) |

`TokenPair = {access_token, refresh_token, token_type: "bearer", expires_in}`. Access tokens last 15 min.
Refresh tokens last 30 days and rotate on every use. Reusing a rotated token revokes that token family
(theft detection). When refresh fails, the app calls `/auth/device` again with the same credentials.
A known `device_id` with the wrong secret gets `401`.

## Users 🔒

| Method | Path | Notes |
|---|---|---|
| GET / PATCH | `/users/me` | Profile: `display_name` (default "Listener"), `avatar_url`, `country` |
| DELETE | `/users/me` | Permanently deletes this device's account and all its data. The next `/auth/device` call starts a fresh, empty account. |
| GET / PATCH | `/users/me/preferences` | `{languages[], audio_quality: low\|medium\|high\|very_high, allow_explicit}` |
| GET / PATCH | `/users/me/notifications` | `{new_releases, recommendations, followed_artists}` |
| PUT / GET | `/users/me/devices` | Register/list devices `{installation_id, platform, name?, push_token?}` |

## Music discovery (auth optional; personalised when signed in)

| Method | Path | Notes |
|---|---|---|
| GET | `/home?languages=English,Hindi` | Sections: recently played, made for you, trending, new releases, charts, trending artists, regional. Per-section provider failures are listed in `errors`; languages whose songs could not be loaded (provider busy, no earlier copy) are listed in `unavailable_languages`. |
| GET | `/search?q=&limit=10&save=false` | `{songs, albums, artists, playlists, errors}`. `save=true` stores the query in search history (signed in). |
| GET | `/songs/{seokey}` | Track |
| GET | `/albums/{seokey}` | Album with tracks |
| GET | `/albums/{album_id}/similar` | Numeric album id |
| GET | `/artists/{seokey}?limit=10` | Artist, top tracks, similar artists, `is_followed` |
| GET | `/artists/{artist_id}/tracks?page=1&limit=20` | Numeric artist id; `{items, page, limit, has_more}` |
| GET | `/playlists/{seokey}` | Provider/chart playlist with tracks |
| GET | `/trending?language=&limit=` | Defaults to the user's first language; `limit` defaults to the home row size and shares one cached fetch per language |
| GET | `/new-releases?language=` | `{language, tracks, albums}` |
| GET | `/charts?limit=20` | Chart playlists |
| GET | `/recommendations` 🔒 | Rule-based; `personalized: false` with an explanation when there is no listening data yet |

## Library 🔒

| Method | Path | Notes |
|---|---|---|
| POST / DELETE | `/library/liked/{song_id}` | Idempotent |
| GET | `/library/liked?offset=&limit=` | `{items: [{track, liked_at}], total}` |
| GET | `/library/liked/status?ids=a,b` | `{a: true, b: false}` |
| GET | `/library/followed-artists` | |
| POST / DELETE | `/library/followed-artists/{artist_seokey}` | 204 |
| GET | `/library/recently-played?limit=` | Distinct tracks, newest first |
| GET / DELETE | `/library/history?offset=&limit=` | Full listening history |
| GET / DELETE | `/library/search-history[?entry_id=]` | |

## User playlists 🔒

| Method | Path | Notes |
|---|---|---|
| GET | `/library/playlists` | Summaries (`track_count`, mosaic `artwork`) |
| GET | `/library/playlists/{id}` | Detail with ordered `tracks: [{track, position, added_at}]` |
| POST | `/playlists` | `{name, description?, is_public?}` → 201 |
| PUT | `/playlists/{id}` | Rename / edit |
| DELETE | `/playlists/{id}` | 204 |
| POST | `/playlists/{id}/songs` | `{song_ids: [...]}` → `{added, already_present, failed, playlist}` |
| DELETE | `/playlists/{id}/songs/{song_id}` | Positions are renumbered |
| PUT | `/playlists/{id}/order` | `{song_ids}`: the full list in its new order |

Playlist changes lock the playlist row (PostgreSQL `SELECT … FOR UPDATE`), so concurrent edits keep
positions consistent.

## Playback 🔒

| Method | Path | Notes |
|---|---|---|
| GET | `/playback/stream/{song_id}?quality=` | `{url, quality, requested_quality, bitrate_kbps, expires_at, available_qualities, format: "hls"}` |
| POST | `/playback/session` | Upsert this device's `{queue[], current_index, position_seconds, shuffle, repeat_mode, quality, context, installation_id}` |
| POST | `/playback/progress` | `{session_id?, song_id, position_seconds, current_index?}` |
| POST | `/playback/complete` | `{song_id, seconds_listened, completed, context?}`; plays under 5 s are ignored (`recorded: false`) |
| GET | `/playback/queue[?session_id=]` | Queue with track metadata; unavailable ids are listed separately |
| GET | `/lyrics/{song_id}` | `{available, synced, instrumental, lines: [{time_ms, text}], plain_text, source}` |

**Stream URLs:** the app streams HLS directly from the provider CDN. The backend never proxies or stores
audio. URLs carry a token that expires about 4 hours after it is issued (`expires_at`); call the endpoint
again before then. Before returning a quality, the backend checks that its HLS playlist actually exists.
If it doesn't, the backend steps down to the next quality that does, and reports it in `quality`.

**Lyrics:** sourced from LRCLIB. `synced` is true only when LRCLIB has real timestamps; plain lyrics
never get invented timings.
