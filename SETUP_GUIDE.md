# Setup guide

```
mobile/        Flutter app (Android + iOS)
backend/       FastAPI backend (PostgreSQL, Redis, Alembic)
third_party/   Vendored GaanaPy (GPL-3.0) + local patch
deploy/        nginx config
docker-compose.yml
```

## 1. Local development

### Requirements
Python 3.12+, Flutter 3.38+ (tested with 3.47), PostgreSQL 15+, optionally Redis and Docker.

### GaanaPy (music provider service)
```bash
cd third_party/GaanaPy
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # Linux/macOS: .venv/bin/pip
.venv/Scripts/python -m uvicorn app:app --port 8001
```
This copy includes fixes that aren't upstream yet ([`third_party/patches/gaanapy-local-fixes.patch`](third_party/patches/gaanapy-local-fixes.patch),
[`third_party/patches/gaanapy-request-cap.patch`](third_party/patches/gaanapy-request-cap.patch)).
The request cap keeps at most `GAANA_MAX_CONCURRENT` (default 4) requests to Gaana in flight, because
bursts are what get the server rate-limited or blocked.
The upstream commit is in `third_party/GAANAPY_UPSTREAM_COMMIT`.

### Backend
```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt
cp .env.example .env            # set DATABASE_URL, JWT_SECRET, GAANAPY_BASE_URL
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python run_dev.py # http://localhost:8000/docs
```
`run_dev.py` exists because, on Windows, the async PostgreSQL driver (psycopg) needs a selector event
loop. On Linux/macOS, `uvicorn app.main:app --reload` works too. Without `REDIS_URL`, the backend uses
an in-process cache, which is fine for a single dev process.

### Flutter app
```bash
cd mobile
flutter pub get
# Android emulator reaches the host at 10.0.2.2 (the default):
flutter run
# Physical device / other host:
flutter run --dart-define=API_BASE_URL=http://192.168.1.20:8000/api/v1
```
Cleartext HTTP is only allowed to `10.0.2.2`, `localhost` and `127.0.0.1` (Android
`network_security_config.xml`, iOS `NSAllowsLocalNetworking`). For a device on your LAN, use HTTPS or add
the host to those configs for development only.

## 2. Tests

```bash
# Backend: SQLite by default
cd backend && .venv/Scripts/python -m pytest
# Backend against PostgreSQL
TEST_DATABASE_URL=postgresql+psycopg://melodia:melodia@localhost:5432/melodia_test .venv/Scripts/python -m pytest
# Backend against the live provider (needs GaanaPy running and Gaana reachable)
LIVE_PROVIDER=1 GAANAPY_BASE_URL=http://localhost:8001 .venv/Scripts/python -m pytest -m live

# Flutter
cd mobile && flutter analyze && flutter test
```
Backend tests replay real GaanaPy responses recorded in `backend/app/tests/fixtures` through the real
client and normaliser, and replace stream-token expiry with a future time.

## 3. Production deployment (Docker)

```bash
cp .env.example .env     # set POSTGRES_PASSWORD and JWT_SECRET (long random)
docker compose up -d --build
docker compose logs -f backend
```
The backend container runs `alembic upgrade head` on start, then serves with uvicorn behind nginx.

### HTTPS
1. Point DNS for your domain at the server and replace `api.example.com` in `deploy/nginx/nginx.conf`.
2. Get certificates, for example with certbot in webroot mode against the `certbot-www` volume, or with any ACME
   client, then place `fullchain.pem` and `privkey.pem` in `deploy/certs/`.
3. `docker compose restart nginx`. Renew with a cron job (`certbot renew` + `nginx -s reload`).

### Environment variables
See `backend/.env.example` (all backend settings) and `.env.example` (compose). Key ones:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | `postgresql+psycopg://user:pass@host:5432/db` |
| `REDIS_URL` | Shared cache and rate limits. Required with more than one worker or instance. |
| `JWT_SECRET` | Signs access tokens. Long and random; rotating it signs everyone out. |
| `GAANAPY_BASE_URL` | URL of the GaanaPy service |
| `VERIFY_STREAM_QUALITY` | Check that each HLS quality exists before returning it |
| `LYRICS_USER_AGENT` | LRCLIB asks clients to identify themselves |
| `WEB_CONCURRENCY` | uvicorn workers |

Secrets are only read from the environment and never committed (`.env` is git-ignored).

### Migrations
```bash
docker compose exec backend alembic upgrade head        # apply
docker compose exec backend alembic downgrade -1        # roll back one
# after changing models (dev):
alembic revision --autogenerate -m "describe change" && alembic check
```

### Logging and health
* One access log line per request with a request id (`X-Request-ID` is propagated from nginx).
* `GET /health` is liveness (also the Docker HEALTHCHECK). `GET /health/ready` checks the DB, cache and
  provider, and is only reachable from localhost through nginx.

### Housekeeping
Run daily (cron or a scheduled container):
```bash
docker compose exec backend python -m app.workers.maintenance
```
It purges expired/revoked tokens and old playback sessions, and trims history older than
`HISTORY_RETENTION_DAYS` (default 730).

### Backup and recovery
```bash
# nightly logical backup
docker compose exec -T postgres pg_dump -U melodia -Fc melodia > backup-$(date +%F).dump
# restore into an empty database
docker compose exec -T postgres pg_restore -U melodia -d melodia --clean --if-exists < backup-YYYY-MM-DD.dump
```
Keep backups off the server and test a restore regularly. Redis only holds cache and rate-limit
counters, so it needs no backup.

## 4. Mobile release notes
* Android: set your own `applicationId` (currently `com.melodia.melodia`) and signing config, then run
  `flutter build appbundle --dart-define=API_BASE_URL=https://api.example.com/api/v1`.
* iOS: open `ios/Runner.xcworkspace`. Background audio and the `melodia://` URL scheme are already in
  `Info.plist`. Set your team and bundle id.
* Android 13+: media-session playback notifications are exempt from the runtime notification
  permission. `POST_NOTIFICATIONS` is declared only for future non-media notifications.
