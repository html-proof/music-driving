"""Transparent rule-based recommendations.

Signals (all from the user's own data):
  * artists in listening history (last 90 days)   weight 1 per play (completed plays 1.5)
  * artists of liked songs                        weight 3
  * followed artists                              weight 4
  * genres / languages of listened + liked songs  used for scoring and trending candidates
Candidates come from the provider: top tracks of the strongest artists, tracks by artists
similar to the strongest artist, and trending tracks in the user's languages that match
their genres. Songs played in the last 7 days or already liked are excluded. Each item
carries a human-readable reason. With no signals at all, nothing personalised is returned.
"""

import asyncio
import logging
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.errors import ProviderError
from app.models import FollowedArtist, LikedSong, ListeningHistory, Song, UserPreferences
from app.schemas.music import Recommendation, Recommendations, Track
from app.services.catalog_service import CatalogService

log = logging.getLogger(__name__)


def _split(v: str | None) -> list[str]:
    return [p.strip() for p in (v or "").split(",") if p.strip()]


class RecommendationService:
    def __init__(self, db: AsyncSession, catalog: CatalogService, user_id: uuid.UUID):
        self.db = db
        self.catalog = catalog
        self.user_id = user_id

    async def _signals(self):
        since = datetime.now(UTC) - timedelta(days=90)
        artist_w: Counter[tuple[str, str, str]] = Counter()  # (seokey, numeric_id, name)
        genres: Counter[str] = Counter()
        languages: Counter[str] = Counter()
        exclude: set[str] = set()

        history = (
            await self.db.execute(
                select(ListeningHistory, Song)
                .join(Song, Song.id == ListeningHistory.song_id)
                .where(ListeningHistory.user_id == self.user_id, ListeningHistory.played_at >= since)
            )
        ).all()
        recent_cutoff = datetime.now(UTC) - timedelta(days=7)
        for h, s in history:
            w = 1.5 if h.completed else 1.0
            self._add_song(s, w, artist_w, genres, languages)
            played = h.played_at if h.played_at.tzinfo else h.played_at.replace(tzinfo=UTC)
            if played >= recent_cutoff:
                exclude.add(s.provider_id)

        liked = (
            await self.db.scalars(
                select(Song).join(LikedSong, LikedSong.song_id == Song.id).where(LikedSong.user_id == self.user_id)
            )
        ).all()
        for s in liked:
            self._add_song(s, 3.0, artist_w, genres, languages)
            exclude.add(s.provider_id)

        followed = (await self.db.scalars(select(FollowedArtist).where(FollowedArtist.user_id == self.user_id))).all()
        for f in followed:
            artist_w[(f.artist.provider_id, f.artist.provider_numeric_id or "", f.artist.name)] += 4.0

        prefs = await self.db.get(UserPreferences, self.user_id)
        return artist_w, genres, languages, exclude, prefs

    @staticmethod
    def _add_song(s: Song, w: float, artist_w: Counter, genres: Counter, languages: Counter) -> None:
        names, keys, ids = _split(s.artists), _split(s.artist_seokeys), _split(s.artist_ids)
        for i, key in enumerate(keys):
            name = names[i] if i < len(names) else key
            numeric = ids[i] if i < len(ids) else ""
            artist_w[(key, numeric, name)] += w
        for g in _split(s.genres):
            genres[g] += w
        if s.language:
            languages[s.language] += w

    async def recommend(self, limit: int = 30) -> Recommendations:
        artist_w, genres, languages, exclude, prefs = await self._signals()
        if not artist_w and not genres:
            return Recommendations(
                personalized=False,
                message="Play, like or follow some music and personalised recommendations will appear here.",
            )
        allow_explicit = prefs.allow_explicit if prefs else True
        top_artists = [a for a, _ in artist_w.most_common(6) if a[1]][:4]
        top_genres = [g for g, _ in genres.most_common(3)]
        langs = [lang for lang, _ in languages.most_common(2)] or (prefs.languages[:2] if prefs else [])

        jobs: list[tuple[str, asyncio.Future]] = []
        for key, numeric, name in top_artists:
            jobs.append((f"Because you listen to {name}", self.catalog.artist_tracks(numeric, 15, 1)))
        if top_artists:
            key, numeric, name = top_artists[0]
            jobs.append((f"similar:{name}", self.catalog.similar_artists_for(numeric)))
        for lang in langs:
            # Same list the home feed shows (one cached fetch per language, no extra Gaana calls).
            jobs.append((f"Trending in {lang}", self.catalog.trending(lang)))

        results = await asyncio.gather(*[j for _, j in jobs], return_exceptions=True)
        buckets: list[list[Recommendation]] = []
        similar_jobs = []
        for (reason, _), res in zip(jobs, results, strict=True):
            if isinstance(res, ProviderError):
                log.info("recommendation source failed (%s): %s", reason, res)
                continue
            if isinstance(res, BaseException):
                raise res
            if reason.startswith("similar:"):
                seed = reason.split(":", 1)[1]
                for artist in res[:2]:
                    if artist.numeric_id:
                        similar_jobs.append((f"Similar to {seed}: {artist.name}",
                                             self.catalog.artist_tracks(artist.numeric_id, 8, 1)))
                continue
            items = res.items if hasattr(res, "items") else res
            if reason.startswith("Trending in") and top_genres:
                items = [t for t in items if set(t.genres) & set(top_genres)]
                reason = f"{reason} · matches your taste for {', '.join(top_genres[:2])}"
            buckets.append([Recommendation(track=t, reason=reason) for t in items])

        if similar_jobs:
            sim = await asyncio.gather(*[j for _, j in similar_jobs], return_exceptions=True)
            for (reason, _), res in zip(similar_jobs, sim, strict=True):
                if not isinstance(res, BaseException):
                    buckets.append([Recommendation(track=t, reason=reason) for t in res.items])

        # Round-robin across sources for variety, skipping excluded / duplicate / disallowed songs.
        seen: set[str] = set(exclude)
        out: list[Recommendation] = []
        while len(out) < limit and any(buckets):
            for bucket in buckets:
                while bucket:
                    rec = bucket.pop(0)
                    t: Track = rec.track
                    if t.id in seen or not t.playable or (t.is_explicit and not allow_explicit):
                        continue
                    seen.add(t.id)
                    out.append(rec)
                    break
                if len(out) >= limit:
                    break
            buckets = [b for b in buckets if b]

        return Recommendations(
            personalized=True,
            message=None if out else "Not enough matching music from the provider right now.",
            items=out,
            based_on={
                "artists": [name for _, _, name in top_artists],
                "genres": top_genres,
                "languages": langs,
            },
        )
