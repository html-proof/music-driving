# Melodia

A music streaming app with a Spotify-style interface: a Flutter app (Android/iOS), a FastAPI backend
(PostgreSQL, Redis), and a swappable music provider: the public [Audius](https://audius.co) API by default,
or [GaanaPy](https://github.com/ZingyTomato/GaanaPy) (`MUSIC_PROVIDER=gaana`).

```
Flutter app ──HTTPS──▶ nginx ──▶ FastAPI backend ──▶ Audius API (or GaanaPy service ──▶ Gaana)
   │                                  │  ├─ PostgreSQL (users, playlists, likes, history, sessions)
   │                                  │  ├─ Redis (catalogue cache, rate limits)
   │                                  │  └─ LRCLIB (synced lyrics)
   └──────────── audio streamed directly from the provider (never proxied): Audius MP3, Gaana HLS
```

* The app only talks to our backend. The backend is the only component that knows about the provider,
  through an adapter (`backend/app/integrations/provider.py`; implementations in `integrations/audius` and
  `integrations/gaanapy`).
* One audio engine (`mobile/lib/features/player/audio_handler.dart`) serves the full player, mini player,
  notification, lock screen and headset/Bluetooth buttons.

Docs: [SETUP_GUIDE.md](SETUP_GUIDE.md) · [API_DOCUMENTATION.md](API_DOCUMENTATION.md) ·
[DEVELOPMENT_PROGRESS.md](DEVELOPMENT_PROGRESS.md) (status, test results, known limitations).

**Licensing:** Audius music is uploaded by the artists, who choose what is streamable; the app plays only
tracks offered as free full streams and identifies itself with `app_name`. GaanaPy is an unofficial API (GPL-3.0). It is vendored in `third_party/` and runs as a
separate service, with a small local fix patch. Having a stream URL doesn't license you to redistribute or publicly stream the
recordings. See *Known limitations* before any public release.
