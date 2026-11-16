"""Local development server.

Equivalent to `uvicorn app.main:app`, but forces a selector event loop on Windows so the
async psycopg driver works. In Docker/Linux just use uvicorn directly.
"""

import asyncio
import os

import uvicorn

from app.runtime import selector_loop_factory

if __name__ == "__main__":
    config = uvicorn.Config(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
        log_level=os.getenv("LOG_LEVEL", "info").lower(),
        proxy_headers=True,
    )
    server = uvicorn.Server(config)
    asyncio.run(server.serve(), loop_factory=selector_loop_factory())
