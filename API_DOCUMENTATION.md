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
| 502 | The music provider failed internally (`{"detail": "Music provider error"}`) |
| 503 | Music provider unavailable (`Retry-After` header). Never reported as "no results". |

**Music provider.** `MUSIC_PROVIDER=gaana` (with the GaanaPy service running) is required for the
Indian film / label and international catalogue (e.g. "Tum Hi Ho", "Malare", "Taylor Swift"). The
default, `audius`, only has music uploaded to Audius by its artists.

## Identifiers

* **Songs, albums, artists, provider playlists** use the provider's id as `id`: the Gaana **seokey** (e.g.
  `tyler-herro`) or the Audius hash id (e.g. `J7Xb000`). Audius `numeric_id`s are hash ids too.
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

* `playable` means "may be streamed": it is `true` unless the provider reports the song as
  unstreamable. Rows in search results and most lists are *lite* rows built from one provider
  list request: no stream, `album: null`, artists without ids, and `duration: 0`.
* `duration: 0` means **unknown**, not 0:00. The real length is known once the stream is loaded.
* A song stored from a different provider (e.g. liked before `MUSIC_PROVIDER` changed) has
  `playable: false`, and it is left out of recently played and recommendations.

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
| GET | `/home?languages=Malayalam,Hindi` | `HomeFeed` (below). `languages` overrides the user's preferences. |
| GET | `/search?q=&type=all&page=1&limit=10&save=false` | `SearchResults` (below). `save=true` stores the query in search history (signed in). |
| GET | `/songs/{seokey}` | Track |
| GET | `/albums/{seokey}` | Album with tracks |
| GET | `/albums/{album_id}/similar` | Numeric album id |
| GET | `/artists/{seokey}?limit=10` | Artist, top tracks, similar artists, `is_followed` |
| GET | `/artists/{artist_id}/tracks?page=1&limit=20` | Numeric artist id; `{items, page, limit, has_more}` |
| GET | `/playlists/{seokey}` | Provider/chart playlist with tracks |
| GET | `/trending?language=&limit=` | Defaults to the user's first language (Audius: a language, genre or `All`, as on Home); `limit` defaults to the home row size and shares one cached fetch per language |
| GET | `/new-releases?language=` | `{language, tracks, albums}` |
| GET | `/charts?limit=20` | Chart playlists |
| GET | `/recommendations` 🔒 | Rule-based; `personalized: false` with an explanation when there is no listening data yet |

### Search

`q` is any text, in any script (1–200 characters; control characters are removed and whitespace
collapsed). `type` is `all` (default), `songs`, `albums`, `artists` or `playlists`: with anything
but `all`, only that section is searched and filled. `page` is 1–20, `limit` 1–30.

```jsonc
{ "query": "മലരേ", "type": "songs", "page": 1,
  "alt_query": "malare",          // Latin form of an Indic-script query, also searched (else null)
  "songs": [Track], "albums": [AlbumSummary], "artists": [ArtistSummary], "playlists": [PlaylistSummary],
  "errors": {"albums": "Music provider is currently unavailable"},   // per section; never shown as "no results"
  "has_more": {"songs": true} }   // another page may exist for that section
```

* Queries in Devanagari, Bengali, Gurmukhi, Gujarati, Oriya, Tamil, Telugu, Kannada or
  Malayalam script are searched in both forms; the Latin results come first, without duplicates.
* An empty section with no `errors` entry means the provider found nothing.
* `errors.query` is set when the query is empty after cleaning.
* Each section has its own deadline (`SEARCH_SECTION_TIMEOUT_SECONDS`, default 10 s).
* Gaana has no playlist search: `playlists` matches chart titles.

### Home

```jsonc
{ "greeting": "Good evening, Listener",
  "languages": ["Malayalam", "Hindi", "Tamil", "Telugu", "Punjabi", "English"],
  "sections": [HomeSection],
  "errors": {"trending_tamil": "Music provider is currently unavailable"},
  "unavailable_languages": ["Tamil"],      // rows that could not be loaded and had no earlier copy
  "generated_at": "2026-11-16T14:03:11Z" }
// HomeSection
{ "id": "trending_malayalam", "title": "Trending in Malayalam", "subtitle": null,
  "type": "tracks",               // tracks | albums | artists | playlists
  "stale": false,                 // true: last good copy, served while the provider is unavailable
  "tracks": [], "albums": [], "artists": [], "playlists": [] }
```

Section ids, in display order (rows with nothing to show are left out):

| id | Row |
|---|---|
| `recently_played` | Signed in; the active provider's songs only |
| `made_for_you` | Signed in, with listening data |
| `trending_<language>` | "Trending in <Language>" for the user's languages first, then `HOME_LANGUAGES`, up to 6 rows. The first comes here; the others come after `charts` |
| `new_tracks_<language>`, `new_albums_<language>` | New songs and albums (each up to the row size) for the first language |
| `international_hits` | "International hits": trending in `INTERNATIONAL_LANGUAGE` (English) |
| `new_tracks_english`, `new_albums_english` | New international songs and albums |
| `top_artists` | "Popular artists": the artists named most often in the trending rows |
| `popular_albums` | Albums of trending songs, only when the provider said which album a song is on |
| `charts` | "Top charts" |

Each provider row has its own deadline (`HOME_SECTION_TIMEOUT_SECONDS`, default 12 s). A row that
fails or is late falls back to its last good copy (`stale: true`); if there is none, the row is
left out and named in `errors` (and its language in `unavailable_languages`). Home itself does not
fail because of one row.

Audius has no languages: Indian language names (`Hindi`, `Tamil`, `Telugu`, `Punjabi`, `Bengali`,
`Marathi`, `Kannada`, `Malayalam`, `Gujarati`) give rows of the most played Audius songs that name
the language, genre names (`Jazz`, `Pop`, ...) give genre rows, and `international_hits` is the
all-genre trending list. Its new releases are global (`new_*_english` only).

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
| POST | `/library/search-history` | `{query}` → 204. Records a search without running it (e.g. when a result is tapped) |

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
| GET | `/playback/stream/{song_id}?quality=` | `{url, quality, requested_quality, bitrate_kbps, expires_at, available_qualities, format}`; `format` is `mp3` (Audius) or `hls` (Gaana) |
| POST | `/playback/session` | Upsert this device's `{queue[], current_index, position_seconds, shuffle, repeat_mode, quality, context, installation_id}` |
| POST | `/playback/progress` | `{session_id?, song_id, position_seconds, current_index?}` |
| POST | `/playback/complete` | `{song_id, seconds_listened, completed, context?}`; plays under 5 s are ignored (`recorded: false`) |
| GET | `/playback/queue[?session_id=]` | Queue with track metadata; unavailable ids are listed separately |
| GET | `/lyrics/{song_id}` | `{available, synced, instrumental, lines: [{time_ms, text}], plain_text, source}` |

**Stream URLs:** the app streams directly from the provider; the backend never proxies or stores audio.
**Audius** (default): one progressive MP3 per track, `quality: high`, no `expires_at`. The URL is Audius'
stream endpoint, which redirects to a fresh signed file each time it is opened. **Gaana**: HLS. URLs carry a token that expires about 4 hours after it is issued (`expires_at`); call the endpoint
again before then. Before returning a quality, the backend checks that its HLS playlist actually exists.
If it doesn't, the backend steps down to the next quality that does, and reports it in `quality`.

**Lyrics:** sourced from LRCLIB. `synced` is true only when LRCLIB has real timestamps; plain lyrics
never get invented timings.
