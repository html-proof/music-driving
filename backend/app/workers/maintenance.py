"""Periodic housekeeping. Run from cron / a scheduled container:

    python -m app.workers.maintenance

* deletes expired or long-revoked refresh tokens
* trims listening history older than HISTORY_RETENTION_DAYS (default 730)
* deletes playback sessions untouched for 90 days
"""

import asyncio
import logging
import os
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, or_

from app.database import dispose_engine, get_sessionmaker, init_engine
from app.models import ListeningHistory, PlaybackSession, RefreshToken
from app.runtime import selector_loop_factory

log = logging.getLogger("maintenance")


async def run() -> dict[str, int]:
    init_engine()
    now = datetime.now(UTC)
    retention = int(os.getenv("HISTORY_RETENTION_DAYS", "730"))
    counts: dict[str, int] = {}
    async with get_sessionmaker()() as db:
        r = await db.execute(
            delete(RefreshToken).where(
                or_(RefreshToken.expires_at < now, RefreshToken.revoked_at < now - timedelta(days=7))
            )
        )
        counts["refresh_tokens"] = r.rowcount or 0
        r = await db.execute(delete(ListeningHistory).where(ListeningHistory.played_at < now - timedelta(days=retention)))
        counts["listening_history"] = r.rowcount or 0
        r = await db.execute(delete(PlaybackSession).where(PlaybackSession.updated_at < now - timedelta(days=90)))
        counts["playback_sessions"] = r.rowcount or 0
        await db.commit()
    await dispose_engine()
    return counts


if __name__ == "__main__":
    logging.basicConfig(level="INFO")
    log.info("maintenance done: %s", asyncio.run(run(), loop_factory=selector_loop_factory()))
