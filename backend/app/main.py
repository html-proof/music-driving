import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import Settings, get_settings
from app.database import dispose_engine, get_engine, init_engine
from app.integrations.audius.client import AudiusClient
from app.integrations.audius.provider import AudiusProvider
from app.integrations.errors import ProviderError, ProviderNotFound, ProviderUnavailable
from app.integrations.gaanapy.client import GaanaPyClient
from app.integrations.gaanapy.provider import GaanaProvider
from app.middleware.request_context import RequestContextMiddleware
from app.routers import auth, library, music, playback, users
from app.services.cache import build_cache
from app.services.catalog_service import CatalogService
from app.services.lyrics_service import LyricsService

API_PREFIX = "/api/v1"


def configure_logging(level: str) -> None:
    logging.basicConfig(level=level.upper(), format="%(asctime)s %(levelname)s %(name)s %(message)s")


def make_stream_probe(client: httpx.AsyncClient):
    async def probe(url: str) -> bool:
        try:
            resp = await client.get(url, timeout=8)
            return resp.status_code == 200 and resp.text.lstrip().startswith("#EXTM3U")
        except httpx.HTTPError:
            return False

    return probe


def create_app(settings: Settings | None = None, provider=None, lyrics: LyricsService | None = None,
               stream_probe=None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        init_engine(settings.database_url)
        cache = build_cache(settings.redis_url, namespace=provider.name if provider else settings.music_provider)
        probe_client = httpx.AsyncClient(follow_redirects=True)
        provider_client = None
        prov = provider
        if prov is None and settings.music_provider == "audius":
            provider_client = AudiusClient(settings.audius_base_url, settings.audius_app_name,
                                           settings.provider_timeout_seconds, settings.provider_retries)
            prov = AudiusProvider(provider_client)
        elif prov is None:
            provider_client = GaanaPyClient(settings.gaanapy_base_url, settings.provider_timeout_seconds,
                                            settings.provider_retries,
                                            block_cooldown_seconds=settings.provider_block_cooldown_seconds,
                                            block_cooldown_max_seconds=settings.provider_block_cooldown_max_seconds)
            prov = GaanaProvider(provider_client)
        app.state.settings = settings
        app.state.cache = cache
        app.state.provider = prov
        app.state.catalog = CatalogService(prov, cache, settings, stream_probe or make_stream_probe(probe_client))
        app.state.lyrics = lyrics or LyricsService(settings.lyrics_base_url, settings.lyrics_user_agent, cache,
                                                   settings.lyrics_enabled)
        yield
        await probe_client.aclose()
        if provider_client:
            await provider_client.close()
        if lyrics is None:
            await app.state.lyrics.close()
        await cache.close()
        await dispose_engine()

    app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan,
                  docs_url="/docs", openapi_url="/openapi.json")
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(ProviderNotFound)
    async def _not_found(_: Request, exc: ProviderNotFound):
        return JSONResponse(status_code=404, content={"detail": str(exc) or "Not found at music provider"})

    @app.exception_handler(ProviderUnavailable)
    async def _unavailable(_: Request, exc: ProviderUnavailable):
        logging.getLogger("app.provider").warning("provider unavailable: %s", exc)
        return JSONResponse(status_code=503, content={"detail": "Music provider is currently unavailable"},
                            headers={"Retry-After": "30"})

    @app.exception_handler(ProviderError)
    async def _provider_error(_: Request, exc: ProviderError):
        # Neither "not found" nor "unavailable": the provider failed internally.
        logging.getLogger("app.provider").error("provider error: %s", exc)
        return JSONResponse(status_code=502, content={"detail": "Music provider error"})

    @app.get("/health", tags=["health"])
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/health/ready", tags=["health"])
    async def ready(request: Request) -> JSONResponse:
        checks = {}
        try:
            async with get_engine().connect() as conn:
                await conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:  # report, don't crash, the readiness probe
            checks["database"] = f"error: {type(exc).__name__}"
        checks["cache"] = "ok" if await request.app.state.cache.ping() else "error"
        checks["music_provider"] = "ok" if await request.app.state.provider.health() else "error"
        healthy = all(v == "ok" for v in checks.values())
        return JSONResponse(status_code=200 if healthy else 503,
                            content={"status": "ok" if healthy else "degraded", "checks": checks})

    for r in (auth.router, users.router, music.router, library.router, playback.router):
        app.include_router(r, prefix=API_PREFIX)
    return app


app = create_app()
