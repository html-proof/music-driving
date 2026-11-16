import asyncio
import logging
import re
from collections import Counter
from collections.abc import Awaitable
from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.errors import ProviderError, ProviderNotFound
from app.models import User
from app.schemas.music import AlbumSummary, ArtistSummary, HomeFeed, HomeSection, Track
from app.services.catalog_service import CatalogService
from app.services.library_service import LibraryService
from app.services.recommendation_service import RecommendationService

log = logging.getLogger(__name__)

# "Trending in <language>" rows on Home, at most (user's languages first).
MAX_LANGUAGE_ROWS = 6


def greeting(tz: str | None) -> str:
    try:
        now = datetime.now(ZoneInfo(tz)) if tz else datetime.now()
    except (ZoneInfoNotFoundError, ValueError):
        now = datetime.now()
    if 5 <= now.hour < 12:
        return "Good morning"
    if 12 <= now.hour < 18:
        return "Good afternoon"
    return "Good evening"


def _filter_explicit(tracks: list[Track], allow: bool) -> list[Track]:
    return tracks if allow else [t for t in tracks if not t.is_explicit]


def _slug(language: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", language.lower()).strip("_")


def home_languages(chosen: list[str], defaults: list[str], international: str) -> list[str]:
    """Languages that get a "Trending in" row: the user's own first (title-cased), then
    the configured Home languages, without the international language, at most
    MAX_LANGUAGE_ROWS."""
    out: list[str] = []
    seen = {international.casefold()}
    for lang in [*chosen, *defaults]:
        name = lang.strip().title()
        if name and name.casefold() not in seen:
            seen.add(name.casefold())
            out.append(name)
    return out[:MAX_LANGUAGE_ROWS]


class HomeService:
    """Builds Home from independent rows. Every provider row has its own deadline and
    falls back to its last good copy (marked `stale`); a row that still fails is named
    in `errors` and the rest of Home is returned. Home never fails as a whole."""

    def __init__(self, db: AsyncSession, catalog: CatalogService):
        self.db = db
        self.catalog = catalog

    async def feed(self, user: User | None, languages: list[str] | None, tz: str | None) -> HomeFeed:
        settings = self.catalog.settings
        prefs = user.preferences if user else None
        chosen = languages or (prefs.languages if prefs and prefs.languages else [])
        intl = settings.international_language.strip().title()
        langs = home_languages(chosen, settings.home_language_list, intl)
        provider = self.catalog.provider
        # Gaana's lists follow the language. Audius maps language names to searched
        # language feeds / genres, and its new releases are global (one row is enough).
        by_language = getattr(provider, "uses_languages", True)
        titles = getattr(provider, "section_titles", {})
        allow_explicit = prefs.allow_explicit if prefs else True
        size = settings.home_section_size
        timeout = settings.home_section_timeout_seconds
        errors: dict[str, str] = {}
        unavailable: list[str] = []
        name = user.profile.display_name if user and user.profile else None

        # User-specific rows first (database only; fast).
        recent: list[Track] = []
        if user is not None:
            try:
                recent = await LibraryService(self.db, self.catalog, user.id).recently_played(12)
            except Exception as exc:  # a broken history row must not take Home down
                errors["recently_played"] = _msg(exc)

        # Provider rows (and recommendations) run concurrently, each with a deadline.
        new_langs = ([langs[0]] if langs and by_language else []) + [intl]
        jobs: dict[str, Awaitable] = {f"trending_{_slug(lang)}": self.catalog.trending_state(lang, size, timeout)
                                      for lang in langs}
        jobs["international_hits"] = self.catalog.trending_state(intl, size, timeout)
        for lang in new_langs:
            jobs[f"new_releases_{_slug(lang)}"] = self.catalog.new_releases_state(lang, size, timeout)
        jobs["charts"] = self.catalog.charts_state(size, timeout)
        if user is not None:
            jobs["made_for_you"] = self._made_for_you(user, timeout)
        results = dict(zip(jobs, await asyncio.gather(*jobs.values(), return_exceptions=True), strict=True))

        def ok(key: str):
            """The job's result, or None (its failure noted in `errors`)."""
            res = results[key]
            if isinstance(res, ProviderNotFound):
                return None  # nothing to show is not an error
            if isinstance(res, BaseException):
                errors[key] = _msg(res)
                return None
            return res

        trending: dict[str, HomeSection] = {}
        for lang in langs:
            key = f"trending_{_slug(lang)}"
            res = ok(key)
            tracks = _filter_explicit(res[0], allow_explicit) if res else []
            if tracks:
                trending[lang] = HomeSection(id=key, title=f"Trending in {lang}", type="tracks", tracks=tracks,
                                             stale=res[1])
            elif key in errors:
                unavailable.append(lang)

        res = ok("international_hits")
        intl_tracks = _filter_explicit(res[0], allow_explicit) if res else []
        international = HomeSection(id="international_hits", title="International hits", type="tracks",
                                    tracks=intl_tracks, stale=res[1]) if intl_tracks else None
        if "international_hits" in errors:
            unavailable.append(intl)

        new_rows: dict[str, list[HomeSection]] = {}
        for lang in new_langs:
            res = ok(f"new_releases_{_slug(lang)}")
            if not res:
                continue
            new, stale = res
            subtitle = lang if by_language else None
            rows = []
            tracks = _filter_explicit(new.tracks, allow_explicit)
            if tracks:
                rows.append(HomeSection(id=f"new_tracks_{_slug(lang)}", title=titles.get("new_tracks", "New songs"),
                                        subtitle=subtitle, type="tracks", tracks=tracks, stale=stale))
            if new.albums:
                rows.append(HomeSection(id=f"new_albums_{_slug(lang)}", title=titles.get("new_albums", "New releases"),
                                        subtitle=subtitle, type="albums", albums=new.albums, stale=stale))
            new_rows[lang] = rows

        res = ok("charts")
        charts = HomeSection(id="charts", title=titles.get("charts", "Top charts"), type="playlists",
                             playlists=res[0], stale=res[1]) if res and res[0] else None

        made_for_you = ok("made_for_you") if user is not None else None

        trending_tracks = [t for s in [*trending.values(), international] if s for t in s.tracks]
        artists = await self._popular_artists(trending_tracks, errors)
        albums = _popular_albums(trending_tracks, size)

        # Order: personal rows, the first language, international, artists / albums /
        # charts, then the other languages.
        first = langs[0] if langs else None
        ordered: list[HomeSection | None] = []
        if recent:
            ordered.append(HomeSection(id="recently_played", title="Recently played", type="tracks", tracks=recent))
        ordered.append(made_for_you)
        if first:
            ordered += [trending.get(first), *new_rows.get(first, [])]
        ordered += [international, *new_rows.get(intl, [])]
        if artists:
            ordered.append(HomeSection(id="top_artists", title="Popular artists", type="artists", artists=artists))
        if albums:
            ordered.append(HomeSection(id="popular_albums", title="Popular albums", type="albums", albums=albums))
        ordered.append(charts)
        ordered += [trending.get(lang) for lang in langs[1:]]

        return HomeFeed(
            greeting=f"{greeting(tz)}{', ' + name if name else ''}",
            languages=[*langs, intl],
            sections=[s for s in ordered if s is not None],
            errors=errors,
            unavailable_languages=unavailable,
            generated_at=datetime.now(UTC),
        )

    async def _made_for_you(self, user: User, timeout: float) -> HomeSection | None:
        recs = await asyncio.wait_for(RecommendationService(self.db, self.catalog, user.id).recommend(20), timeout)
        if not (recs.personalized and recs.items):
            return None
        return HomeSection(
            id="made_for_you", title="Made for you",
            subtitle="Based on " + ", ".join(recs.based_on.get("artists", [])[:3]),
            type="tracks", tracks=[r.track for r in recs.items],
        )

    async def _popular_artists(self, tracks: list[Track], errors: dict[str, str]) -> list[ArtistSummary]:
        """The artists named most often across the trending rows. Each card comes from a
        one-row artist search by name (cached for a day), accepted only on an exact name
        match: list rows carry artist names but often no artist ids."""
        counts: Counter[str] = Counter()
        names: dict[str, str] = {}
        for t in tracks:
            for a in t.artists:
                key = a.name.strip().casefold()
                if key:
                    counts[key] += 1
                    names.setdefault(key, a.name.strip())
        wanted = [names[k] for k, _ in counts.most_common(self.catalog.settings.home_artist_count)]
        if not wanted:
            return []
        found = await asyncio.gather(*[self.catalog.artist_by_name(n) for n in wanted], return_exceptions=True)
        artists: list[ArtistSummary] = []
        failures = []
        for res in found:
            if isinstance(res, ProviderNotFound):
                continue
            if isinstance(res, BaseException):
                failures.append(res)
            elif all(a.id != res.id for a in artists):
                artists.append(res)
        if failures and not artists:
            errors["top_artists"] = _msg(failures[0])
        return artists


def _popular_albums(tracks: list[Track], limit: int) -> list[AlbumSummary]:
    """Albums of the trending songs, when the provider said which album a song is on
    (id and artwork); list rows without album data contribute nothing."""
    albums: list[AlbumSummary] = []
    seen: set[str] = set()
    for t in tracks:
        album = t.album
        art = t.artwork
        if not (album and album.id and album.title) or album.id in seen:
            continue
        if not (art.small or art.medium or art.large):
            continue
        seen.add(album.id)
        albums.append(AlbumSummary(id=album.id, numeric_id=album.numeric_id, title=album.title, artwork=art,
                                   language=t.language))
    return albums[:limit]


def _msg(exc: BaseException) -> str:
    if isinstance(exc, ProviderError):
        return "Music provider is currently unavailable"
    if isinstance(exc, TimeoutError):
        return "Music provider is taking too long"
    log.error("home section failed", exc_info=exc)
    return "Unexpected error"
