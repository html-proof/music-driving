# Development progress

Last updated: 2026-11-16

## Phase summary

| Phase | Status | Notes |
|---|---|---|
| 1. GaanaPy audit | ✅ | Every endpoint probed live; findings below |
| 2. Backend | ✅ | FastAPI, provider adapter, Redis/memory cache, rate limits, request logging |
| 3. Database | ✅ | 17 tables, UUID PKs, FKs, unique constraints, indexes, Alembic `0001` (tested up/down/check on PostgreSQL 18) |
| 4. Flutter architecture | ✅ | Riverpod 3, Dio, GoRouter 18, just_audio + audio_service, sqflite, secure storage |
| 5. UI | ✅ | Home, Search, Library, Profile tabs; album/artist/playlist/liked pages; full player, mini player, queue, lyrics |
| 6. Audio engine | ✅ (logic tested; device testing pending) | One `MelodiaAudioHandler` behind every control surface |
| 7. Lyrics | ✅ | LRCLIB with real LRC timestamps; plain lyrics shown as unsynced |
| 8. Mini player / media controls | ✅ | Same handler; notification, lock screen and headset buttons go through `audio_service` |
| 9. Recommendations | ✅ | Transparent rules; returns "not personalised" with no data |
| 10. Performance/reliability | ✅ | Caching, retries, cancellation, offline metadata, skip-on-failure |
| 11. Testing | ✅ automated / ⚠️ device | Backend 49 tests (SQLite + PostgreSQL), Flutter 35 tests; no emulator or device available here |
| 12. Deployment | ✅ | Dockerfile, compose (postgres, redis, gaanapy, backend, nginx), HTTPS, backups, maintenance job |

## Test results (this session)

* Backend `pytest`: **49 passed** on SQLite and **49 passed** on PostgreSQL 18. 3 live tests are
  skipped by default.
* Backend live tests (`-m live`): **failed: Gaana returned HTTP 403 "Access Denied"** to this machine
  after heavy probing (rate limiting/bot protection on `gaana.com/apiv2`). Before the block, every endpoint
  was verified manually against live data, including a real HLS master playlist (`#EXTM3U`) for a song.
* End-to-end against the running stack (PostgreSQL + patched GaanaPy + backend): device sign-in
  (first launch 201, relaunch 200, wrong secret 401), profile, charts, home (partial, with per-section errors), stream resolution (fresh 4 h URL), and
  playlist creation all worked.
* Flutter: `flutter analyze` reports no issues; `flutter test` **35 passed**; `flutter build apk --debug`
  succeeded.
* Not done: real-device or emulator testing of background playback, lock screen, Bluetooth, audio focus
  and headphone unplug. No emulator image or device was available. The code paths are in place and
  unit-tested through a fake engine, but they **must be verified on hardware** before calling them done.

## GaanaPy audit findings

| Endpoint | Result |
|---|---|
| songs search / info | Works. Search is intermittently empty or 404 for valid queries. |
| albums search / info, similar | Works. Album search is flaky. |
| artists search / info / tracks / similar | Works. `total` in artist tracks is the page size, not the total count. |
| trending, new releases | Works. New releases often has no `tracks`, only `albums`. |
| charts | Works (served from `apiv2.gaana.com`, which was not blocked) |
| playlists/info | **Broken upstream**: Gaana now returns `"error": "SUCCESS"` on success. Fixed locally. |
| stream URLs | HLS (`.m3u8`, AAC). Token expires about 4 h after issue. 320/128/16 kbps URLs are derived by string substitution, so the backend verifies them. |
| lyrics | Not provided; LRCLIB integrated instead |
| error handling | **Upstream hides outages as "no results" (404)**. Patched so 403/429/5xx/network errors become 502, which the backend reports as 503. |

Local patch: `third_party/patches/gaanapy-local-fixes.patch`.

## Known limitations

1. **Licensing:** GaanaPy is unofficial and uses Gaana's private web endpoints. A stream URL does not
   grant a licence to stream that recording. This is fine for personal or educational use; public or
   commercial release needs proper licences or a licensed catalogue provider (the provider adapter
   `app/integrations/provider.py` exists so it can be swapped).
2. **Provider availability:** Gaana rate-limits and blocks clients (seen in this session as HTTP 403).
   Catalogue caching (15 min) reduces traffic, but the app depends on Gaana being reachable. The app shows
   "provider unavailable", never fake data.
3. **Search quality:** Only what GaanaPy returns. Playlist search matches chart titles only, because
   GaanaPy has no playlist search.
4. **Downloads / offline audio:** Not implemented. Offline mode covers metadata only (home, liked songs,
   playlists, followed artists, profile). No audio is downloaded, because the provider grants no licence for it.
5. **Push notifications:** Device registration and preferences are stored, but Firebase Cloud
   Messaging isn't wired. It needs your Firebase project (`google-services.json` /
   `GoogleService-Info.plist`) and a sender job.
6. **No sign-in (by design):** Each install gets an anonymous account tied to credentials in the device
   keystore. Uninstalling the app or clearing its data starts a new, empty library, and libraries don't
   move between devices. Android backup can restore keystore entries on some devices, but don't rely on it.
7. **Gapless playback:** Songs load one at a time so each stream URL is fresh when it starts. The next
   URL is prefetched, but there is a short gap between tracks.
8. **Lyrics coverage:** Depends on LRCLIB's crowd-sourced data. Many regional songs have none.
9. **Windows dev quirks:** Async psycopg needs `run_dev.py`. The Kotlin incremental cache is disabled
   (`android/gradle.properties`) because of a cross-drive bug.

## Acceptance criteria

| # | Criterion | Status |
|---|---|---|
| 1 | ~~Register and log in~~ → no sign-in; silent per-device account | ✅ tested (API, client, e2e) |
| 2 | Home loads real music | ✅ verified live (partial during the provider block) |
| 3 | Search returns real songs/albums/artists | ✅ verified live before block; upstream search flaky |
| 4 | Artwork matches song | ✅ album-specific artwork ids asserted in tests |
| 5 | Accurate metadata | ✅ normalised from provider, tested against recorded responses |
| 6 | Actual audio playback | ⚠️ real HLS URL verified; on-device playback not run here |
| 7 | Background playback | ⚠️ configured (foreground service, iOS audio mode); needs a device |
| 8 | Lock-screen controls | ⚠️ media session controls published (tested); needs a device |
| 9 | Mini player | ✅ widget-tested |
| 10 | Main player | ✅ built; controls share the tested handler |
| 11 | Previous/next | ✅ Spotify rule unit- and handler-tested |
| 12 | Seeking | ✅ widget-tested (tap, drag-to-release) |
| 13 | Queue management | ✅ tested (play next, add, remove, reorder, shuffle, repeat) |
| 14 | Create playlists | ✅ tested |
| 15 | Like songs | ✅ tested |
| 16 | History persists | ✅ tested (PostgreSQL) |
| 17 | Lyrics when available | ✅ tested (synced + unavailable states) |
| 18 | State survives navigation and restarts | ✅ queue/position restore tested; tokens and metadata persisted |
| 19 | Data in PostgreSQL | ✅ |
| 20 | No hardcoded sample data | ✅ app code has none; tests use recorded real responses |

## Next steps
1. Run on an Android device or emulator and an iPhone: background, lock screen, Bluetooth, unplug,
   phone-call interruption.
2. Re-run `pytest -m live` once Gaana stops blocking the IP.
3. Decide on licensing before any public release.
4. Optional: FCM, CI pipeline, and a way to move a library to a new phone (e.g. a transfer code).
