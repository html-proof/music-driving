# Root cause: missing search results and an empty Home (2026-11-16)

I checked three layers separately, using live probes from a development machine with an Indian IP and a code audit of every layer.

## 1. GaanaPy and Gaana (data source)

| Finding | Evidence |
|---|---|
| The catalogue is there. All 10 test queries returned correct songs at about 1 s each: Malare, Malayalam songs, Arabic Kuthu, Butta Bomma, Tum Hi Ho, Arijit Singh, The Weeknd, Taylor Swift, BTS and Coldplay. | Live `/songs/search/` |
| **Gaana's Akamai edge blocks the client with HTTP 403 "Access Denied" after about 3 minutes of normal use.** That was a dozen searches and one Home load. `apiv2.gaana.com` (charts) kept answering. | Raw `curl` before and after |
| **Every list is N+1 requests.** A search, trending or new-releases call makes one list request and then one `songDetail`, `albumDetail` or `artistDetail` request per row. The fields needed to show a row (id, seo, title, artwork, artists, language) are already in the list response and get thrown away. One search across songs, albums and artists costs about 33 Gaana requests; one Home load costs about 45 to 135. | `api/songs/songs.py`, `albums/albums.py`, `artists/artists.py`, `trending/trending.py` |
| If one detail request in a list fails, the whole list fails (`asyncio.gather` without `return_exceptions`), and any 5xx turns into a provider-wide cooldown in the backend. | `songs.py:35`, `client.py:100` |
| The query check `^[a-zA-Z0-9\s\-'.&]+$` returns 422 for Malayalam, Tamil, Telugu and Devanagari script, accented names and punctuation. The keyword is concatenated into the URL without encoding, so `&` splits it. | `app.py:49`, `songs.py:7` |
| GaanaPy sends the default `aiohttp` User-Agent and no Origin or Referer, which bot protection flags. | `api/gaanapy.py` |
| Gaana has no playlist search, so playlist search can only match chart titles. Gaana's own search treats Malayalam script poorly: a native-script query returns unrelated Hindi songs. | Live raw search |

## 2. Backend

* The default provider is **Audius** (`MUSIC_PROVIDER=audius`). It was switched in `cf0c368` because Gaana blocked the server. Audius hosts music uploaded by artists, not Indian film or major-label catalogues, so "Tum Hi Ho" and "Taylor Swift" aren't on it.
* `sanitize_query` removes every non-ASCII character, so `മലരേ` became `""`, and the empty result was reported as "no results" with no error.
* Provider failures and 422 responses were cached as "not found" for 15 minutes (`_cached` `miss:` key), so one partial block hid songs that exist (seen live: `Malare` returned 0 songs).
* Home built rows only for the first 3 configured languages (default `English,Hindi`), with no Malayalam, Tamil, Telugu or Punjabi. New releases came only from the first language, and the albums and tracks shared one limit. There were no international or popular-albums rows.
* Timeouts were retried, and each retry started GaanaPy's whole fan-out again. No section had a deadline.

## 3. Flutter

* Tapping a song in search ran the whole search again (another ~33 Gaana requests).
* There were no category tabs, no minimum query length and no pagination. The result size was fixed at 10.
* Home was all-or-nothing behind one spinner. A failed or empty feed overwrote the last good offline copy, and Riverpod and Dio retries multiplied failing calls.

## Conclusion
The missing music isn't a UI bug. The app was pointed at a provider without the catalogue (Audius). Gaana itself is reachable, but it gets blocked because the stack sends it bursts of requests at about 30 times the necessary volume. On top of that, regional-script queries were dropped before they reached Gaana. The fixes cut Gaana traffic to about one request per list, make failures visible and isolated per section, and accept any script.

## Fixes (this change)
* **GaanaPy:**
  * Rows are built from the list or search response: one Gaana request per search section or list, where it used to be 1 + N. The stream is resolved when the song is played.
  * Search accepts any script and is URL-encoded, and has `page`.
  * Requests are paced and list responses are cached for 10 minutes.
  * A circuit breaker stops all calls for 2 to 15 minutes after a 401/403/429.
  * Errors are distinct: 503 blocked, 502 unavailable, 500 internal.
  * One failed lookup no longer discards a whole list.
  * Requests are not disguised as a browser.
* **Backend:**
  * Unicode search with transliteration (`മലരേ` → `malare`, `బుట్ట బొమ్మ` → `butta bomma`, `तुम ही हो` → `tum hi ho`) merged with the native-script results.
  * `type`, `page` and `has_more` on search; per-section deadlines; failures reported in `errors` and never cached as "not found".
  * `POST /library/search-history`.
  * Home has one trending row per Indian language (Hindi, Malayalam, Tamil, Telugu, Punjabi), International hits, new releases per language, charts and popular artists.
  * Home sections time out one at a time and fall back to the last good copy (`stale: true`), and history is filtered by provider.
* **Flutter:**
  * Search: All/Songs/Artists/Albums/Playlists chips with paging, and a request-id guard so old results never overwrite newer ones. Tapping a result plays it and records history without searching again.
  * Home: shows the cached copy first and refreshes, with skeletons, pull-to-refresh, per-section retry, a "saved copy" marker and a "Continue listening" row. A failed or empty feed no longer replaces the saved copy, and automatic retry storms are removed.
  * Artwork now loads on Flutter web.

## Verification
* Automated tests: GaanaPy 137 passed, backend 125 passed (3 live tests skipped), Flutter 125 passed, and `flutter analyze` reports no issues.
* End to end against recorded Gaana responses (Gaana was blocking this machine, so these were replayed): real GaanaPy, then the backend, then the Flutter web build.
  * Searching `മലരേ` showed "Showing results for "malare" too" and the real Malayalam/Tamil "Malare" songs with correct artists and artwork.
  * Paging works.
  * Tapping a song requested that song's own stream id and recorded history without searching again.
* **Not verified live:** the real payload shapes of trending, new releases, album, artist and playlist detail, and audio playback. These need Gaana to accept requests from the host again. The mapper falls back to capped detail lookups for any entry without title or artwork. On-device testing (Android emulator or phone) hasn't been done.

**Remaining limitation (can't be fixed in code):** GaanaPy uses Gaana's private web API. Gaana can and does block IP addresses, including the deployment server (earlier sessions saw 403 there). Lower request volume makes blocks much less likely but can't prevent them.
