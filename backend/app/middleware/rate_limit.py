"""Fixed-window rate limiting on top of the shared cache (Redis in production)."""

import time

from fastapi import HTTPException, Request, status


def rate_limit(name: str, limit: int, window_seconds: int):
    async def dependency(request: Request) -> None:
        settings = request.app.state.settings
        if settings.environment == "test":
            return
        cache = request.app.state.cache
        client = request.client.host if request.client else "unknown"
        window = int(time.time()) // window_seconds
        key = f"ratelimit:{name}:{client}:{window}"
        count = (await cache.get(key) or 0) + 1
        await cache.set(key, count, window_seconds)
        if count > limit:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many requests, please try again later",
                                headers={"Retry-After": str(window_seconds)})

    return dependency
