import asyncio
import logging
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.errors import ProviderError, ProviderNotFound
from app.models import User
from app.schemas.music import HomeFeed, HomeSection, Track
from app.services.catalog_service import CatalogService
from app.services.library_service import LibraryService
from app.services.recommendation_service import RecommendationService

log = logging.getLogger(__name__)


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


class HomeService:
    def __init__(self, db: AsyncSession, catalog: CatalogService):
        self.db = db
        self.catalog = catalog

    async def feed(self, user: User | None, languages: list[str] | None, tz: str | None) -> HomeFeed:
        prefs = user.preferences if user else None
        langs = languages or (prefs.languages if prefs and prefs.languages else self.catalog.settings.default_language_list)
        # Feeds follow languages for Gaana; providers without languages (Audius) map them
        # to genres, falling back to a single all-genre feed.
        provider = self.catalog.provider
        by_language = getattr(provider, "uses_languages", True)
        feeds = langs if by_language else provider.categories_for(langs)
        titles = getattr(provider, "section_titles", {})
        label = (lambda f: f) if by_language else (lambda f: None if f == "All" else f)
        allow_explicit = prefs.allow_explicit if prefs else True
        errors: dict[str, str] = {}
        sections: list[HomeSection] = []
        name = user.profile.display_name if user and user.profile else None

        # User-specific sections first (database only; fast).
        if user is not None:
            library = LibraryService(self.db, self.catalog, user.id)
            recent = await library.recently_played(12)
            if recent:
                sections.append(HomeSection(id="recently_played", title="Recently played", type="tracks", tracks=recent))

        # Provider sections run concurrently; one failure must not blank the page. Each
        # listed song costs one Gaana request when a list is refreshed, so rows are kept
        # short (HOME_SECTION_SIZE) and cached for an hour.
        size = self.catalog.settings.home_section_size
        jobs = {f"trending:{lang}": self.catalog.trending(lang, size) for lang in feeds[:3]}
        jobs[f"new:{feeds[0]}"] = self.catalog.new_releases(feeds[0], size)
        jobs["charts"] = self.catalog.charts(12)
        results = dict(zip(jobs, await asyncio.gather(*jobs.values(), return_exceptions=True), strict=True))

        if user is not None:
            try:
                recs = await RecommendationService(self.db, self.catalog, user.id).recommend(20)
                if recs.personalized and recs.items:
                    sections.append(HomeSection(
                        id="made_for_you", title="Made for you",
                        subtitle="Based on " + ", ".join(recs.based_on.get("artists", [])[:3]),
                        type="tracks", tracks=[r.track for r in recs.items],
                    ))
            except ProviderError as exc:
                errors["made_for_you"] = str(exc)

        trending_tracks: list[Track] = []
        for i, lang in enumerate(feeds[:3]):
            res = results[f"trending:{lang}"]
            if isinstance(res, list) and res:
                tracks = _filter_explicit(res, allow_explicit)
                trending_tracks.extend(tracks)
                sections.append(HomeSection(
                    id=f"trending_{lang.lower()}",
                    title="Trending now" if i == 0 else f"Popular in {lang}",
                    subtitle=label(lang) if i == 0 else ("Regional picks" if by_language else "Genre picks"),
                    type="tracks", tracks=tracks,
                ))
            elif isinstance(res, BaseException) and not isinstance(res, ProviderNotFound):
                errors[f"trending_{lang.lower()}"] = _msg(res)

        new = results[f"new:{feeds[0]}"]
        if not isinstance(new, BaseException):
            if new.albums:
                sections.append(HomeSection(id="new_albums", title=titles.get("new_albums", "New releases"),
                                            subtitle=label(feeds[0]),
                                            type="albums", albums=new.albums))
            if new.tracks:
                sections.append(HomeSection(id="new_tracks", title=titles.get("new_tracks", "New songs"),
                                            subtitle=label(feeds[0]),
                                            type="tracks", tracks=_filter_explicit(new.tracks, allow_explicit)))
        elif not isinstance(new, ProviderNotFound):
            errors["new_releases"] = _msg(new)

        charts = results["charts"]
        if isinstance(charts, list) and charts:
            sections.append(HomeSection(id="charts", title=titles.get("charts", "Top charts"), type="playlists", playlists=charts))
        elif isinstance(charts, BaseException) and not isinstance(charts, ProviderNotFound):
            errors["charts"] = _msg(charts)

        # "Artists trending now": the most frequent artists across the trending tracks.
        counts = Counter(a.id for t in trending_tracks for a in t.artists if a.id)
        artist_keys = [k for k, _ in counts.most_common(self.catalog.settings.home_artist_count)]
        if artist_keys:
            # Cards need only a name and picture: no top tracks or similar artists.
            fetched = await asyncio.gather(*[self.catalog.artist_card(k) for k in artist_keys],
                                           return_exceptions=True)
            artists = [a for a in fetched if not isinstance(a, BaseException)]
            if artists:
                sections.append(HomeSection(
                    id="top_artists", title="Artists trending now", type="artists",
                    artists=[a.model_copy(update={"top_tracks": []}) for a in artists],
                ))

        # Order: recently played, made for you, trending, new, charts, artists, then regional.
        first_trending = f"trending_{feeds[0].lower()}"
        order = ["recently_played", "made_for_you", first_trending, "new_albums", "new_tracks", "charts",
                 "top_artists"]
        sections.sort(key=lambda s: order.index(s.id) if s.id in order else len(order))
        return HomeFeed(
            greeting=f"{greeting(tz)}{', ' + name if name else ''}",
            languages=langs,
            sections=sections,
            errors=errors,
        )


def _msg(exc: BaseException) -> str:
    if isinstance(exc, ProviderError):
        return "Music provider is currently unavailable"
    log.error("home section failed", exc_info=exc)
    return "Unexpected error"
