# Melodia

A music streaming app with a Spotify-style interface: a Flutter app (Android/iOS), a FastAPI backend
(PostgreSQL, Redis), and [GaanaPy](https://github.com/ZingyTomato/GaanaPy) as the music catalogue and
stream provider.

```
Flutter app ──HTTPS──▶ nginx ──▶ FastAPI backend ──▶ GaanaPy service ──▶ Gaana
   │                                  │  ├─ PostgreSQL (users, playlists, likes, history, sessions)
   │                                  │  ├─ Redis (catalogue cache, rate limits)
   │                                  │  └─ LRCLIB (synced lyrics)
   └──────────── HLS audio streamed directly from the provider CDN (never proxied)
```

* The app only talks to our backend. The backend is the only component that knows about GaanaPy, through a
  provider adapter (`backend/app/integrations/provider.py`).
* One audio engine (`mobile/lib/features/player/audio_handler.dart`) serves the full player, mini player,
  notification, lock screen and headset/Bluetooth buttons.

Docs: [SETUP_GUIDE.md](SETUP_GUIDE.md) · [API_DOCUMENTATION.md](API_DOCUMENTATION.md) ·
[DEVELOPMENT_PROGRESS.md](DEVELOPMENT_PROGRESS.md) (status, test results, known limitations).

**Licensing:** GaanaPy is an unofficial API (GPL-3.0). It is vendored in `third_party/` and runs as a
separate service, with a small local fix patch. Having a stream URL doesn't license you to redistribute or publicly stream the
recordings. See *Known limitations* before any public release.
