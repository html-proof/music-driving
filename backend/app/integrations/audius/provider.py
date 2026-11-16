import asyncio
import re
from collections import OrderedDict
from dataclasses import dataclass
from functools import cached_property
from itertools import chain
from typing import ClassVar

from app.integrations.audius import normalize as n
from app.integrations.audius.client import AudiusClient
from app.integrations.errors import ProviderNotFound
from app.integrations.provider import ProviderTrack
from app.schemas.music import (
    AlbumDetail,
    AlbumSummary,
    ArtistDetail,
    ArtistSummary,
    AudioQuality,
    NewReleases,
    PlaylistDetail,
    PlaylistSummary,
    Track,
    TrackPage,
)

# Audius genre names, as accepted by /tracks/trending?genre=.
GENRES = [
    "Electronic", "Hip-Hop/Rap", "Pop", "R&B/Soul", "Lo-Fi", "House", "Rock", "Alternative", "Ambient",
    "Dubstep", "Drum & Bass", "Techno", "Trap", "Jazz", "Acoustic", "Classical", "Latin", "Reggae",
    "Country", "Folk", "Metal", "Soundtrack", "World", "Experimental",
]
def _key(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


_GENRE_KEYS = {_key(g): g for g in GENRES}
ALL = "All"


@dataclass(frozen=True)
class LanguageSearch:
    """How to find a language's songs on Audius, which has no language field.

    `queries` are searched (most played first); Audius search is fuzzy ("kollywood"
    returns Hollywood, "kannada" returns "adanna"), so a track is kept only when its
    title, tags, description or artist name contains one of `words` as a whole word.
    """

    queries: tuple[str, ...]
    words: tuple[str, ...]

    @cached_property
    def _pattern(self) -> re.Pattern:
        alternatives = "|".join(re.escape(w) for w in self.words)
        return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)

    def matches(self, row: dict) -> bool:
        user = row.get("user") if isinstance(row.get("user"), dict) else {}
        text = " ".join(str(v) for v in (row.get("title"), row.get("tags"), row.get("description"),
                                          user.get("name"), user.get("handle")) if v)
        return bool(self._pattern.search(text))


# The app's music languages (mobile AppConfig.supportedLanguages), each with its own
# name in native script. English is Audius's own (mostly English) trending feed.
LANGUAGES: dict[str, LanguageSearch] = {
    "Hindi": LanguageSearch(("hindi", "bollywood"), ("hindi", "bollywood", "हिंदी", "हिन्दी")),
    "Tamil": LanguageSearch(("tamil", "kollywood"), ("tamil", "kollywood", "தமிழ்")),
    "Telugu": LanguageSearch(("telugu", "tollywood"), ("telugu", "tollywood", "తెలుగు")),
    "Punjabi": LanguageSearch(("punjabi", "bhangra"), ("punjabi", "bhangra", "ਪੰਜਾਬੀ")),
    "Bengali": LanguageSearch(("bengali", "bangla"), ("bengali", "bangla", "বাংলা")),
    "Marathi": LanguageSearch(("marathi",), ("marathi", "मराठी")),
    "Kannada": LanguageSearch(("kannada",), ("kannada", "ಕನ್ನಡ")),
    "Malayalam": LanguageSearch(("malayalam", "mollywood"), ("malayalam", "mollywood", "മലയാളം")),
    # Not "garba": also a common surname, so artist names matched unrelated songs.
    "Gujarati": LanguageSearch(("gujarati",), ("gujarati", "ગુજરાતી")),
}
_LANGUAGE_KEYS = {_key(name): name for name in LANGUAGES}
# Each query asks for this many results, so enough survive the word filter.
LANGUAGE_SEARCH_SIZE = 40


def genre_for(category: str | None) -> str | None:
    """The Audius genre matching a category name ("Pop", "Jazz", "Hiphop Rap", ...), or
    None for "every genre"."""
    if not category:
        return None
    return _GENRE_KEYS.get(_key(category))


def language_for(category: str | None) -> str | None:
    """The app language a category names ("Hindi", "tamil", ...), if it is one."""
    return _LANGUAGE_KEYS.get(_key(category)) if category else None


def category_for(name: str) -> str | None:
    """Home feed for one of the user's language preferences: a genre, a searched
    language, or the all-genre feed for English. None when Audius has nothing for it."""
    if genre := genre_for(name):
        return genre
    if language := language_for(name):
        return language
    return ALL if _key(name) == "english" else None


class AudiusProvider:
    name = "audius"
    # Home feeds are genres or searched languages, not provider languages (see `categories_for`).
    uses_languages = False
    # One progressive MP3 per track behind a redirecting endpoint: nothing to verify.
    stream_format = "mp3"
    verify_streams = False
    section_titles: ClassVar[dict[str, str]] = {
        "new_albums": "Top albums", "new_tracks": "Fresh & underground", "charts": "Trending playlists",
    }

    def __init__(self, client: AudiusClient, remember: int = 3000):
        self.client = client
        # Lists already carry full track records; remembering them lets a listed song
        # play without a second /tracks/{id} lookup.
        self._seen: OrderedDict[str, Track] = OrderedDict()
        self._remember_max = remember

    async def health(self) -> bool:
        return await self.client.health()

    def categories_for(self, languages: list[str]) -> list[str]:
        """One Home feed per language preference, in the user's order: genres as genres,
        Indian languages as searched language feeds, English as all-genre trending.
        Falls back to one all-genre feed."""
        feeds = list(dict.fromkeys(c for c in (category_for(lang) for lang in languages) if c))
        return feeds or [ALL]

    @staticmethod
    def is_language(feed: str) -> bool:
        return language_for(feed) is not None

    def _stream(self, t: Track) -> dict[AudioQuality, str]:
        return {AudioQuality.high: self.client.stream_url(t.id)} if t.playable else {}

    def known_track(self, song_id: str) -> ProviderTrack | None:
        t = self._seen.get(song_id)
        return ProviderTrack(t, self._stream(t)) if t else None

    def _tracks(self, rows: list[dict]) -> list[Track]:
        tracks = [n.track(r) for r in rows if isinstance(r, dict) and r.get("id")]
        for t in tracks:
            self._seen[t.id] = t
            self._seen.move_to_end(t.id)
        while len(self._seen) > self._remember_max:
            self._seen.popitem(last=False)
        return tracks

    # --- search -------------------------------------------------------------------
    # Only the first page is served: Audius search paging is not wired up here, so later
    # pages are empty (no request) and the backend reports has_more = false.
    paged_search = False

    async def search_songs(self, query: str, limit: int, page: int = 1) -> list[Track]:
        if page > 1:
            return []
        return self._tracks(await self.client.search_tracks(query, limit))

    async def search_albums(self, query: str, limit: int, page: int = 1) -> list[AlbumSummary]:
        if page > 1:
            return []
        # Albums are playlists flagged is_album; over-fetch, then filter.
        rows = await self.client.search_playlists(query, min(limit * 3, 100))
        return [n.album_summary(r) for r in rows if r.get("is_album")][:limit]

    async def search_artists(self, query: str, limit: int, page: int = 1) -> list[ArtistSummary]:
        if page > 1:
            return []
        return [n.artist_summary(u) for u in await self.client.search_users(query, limit)]

    async def search_playlists(self, query: str, limit: int, page: int = 1) -> list[PlaylistSummary]:
        if page > 1:
            return []
        rows = await self.client.search_playlists(query, min(limit * 2, 100))
        return [n.playlist_summary(r) for r in rows if not r.get("is_album")][:limit]

    # --- items --------------------------------------------------------------------
    async def get_song(self, song_id: str) -> ProviderTrack:
        raw = await self.client.track(song_id)
        if not raw:
            raise ProviderNotFound(f"Song {song_id} not found")
        t = self._tracks([raw])[0]
        return ProviderTrack(t, self._stream(t))

    async def get_album(self, album_id: str) -> AlbumDetail:
        raw, tracks = await asyncio.gather(self.client.playlist(album_id), self.client.playlist_tracks(album_id))
        self._tracks(tracks)
        return n.album_detail(raw, tracks)

    async def similar_albums(self, album_numeric_id: str, limit: int) -> list[AlbumSummary]:
        # No similarity endpoint: other albums by the same artist.
        raw = await self.client.playlist(album_numeric_id)
        owner = (raw.get("user") or {}).get("id")
        if not owner:
            return []
        rows = await self.client.user_albums(owner, limit + 1)
        return [n.album_summary(r) for r in rows if r.get("id") != album_numeric_id][:limit]

    async def get_artist(self, artist_id: str, limit: int) -> ArtistDetail:
        user, top = await asyncio.gather(self.client.user(artist_id),
                                         self.client.user_tracks(artist_id, limit, sort="plays"))
        if not user:
            raise ProviderNotFound(f"Artist {artist_id} not found")
        self._tracks(top)
        return n.artist_detail(user, top)

    async def artist_tracks(self, artist_numeric_id: str, limit: int, page: int) -> TrackPage:
        rows = await self.client.user_tracks(artist_numeric_id, limit, offset=(page - 1) * limit)
        return TrackPage(items=self._tracks(rows), page=page, limit=limit, total=None,
                         has_more=len(rows) >= limit)

    async def similar_artists(self, artist_numeric_id: str, limit: int) -> list[ArtistSummary]:
        return [n.artist_summary(u) for u in await self.client.related_users(artist_numeric_id, limit)]

    async def get_playlist(self, playlist_id: str) -> PlaylistDetail:
        raw, tracks = await asyncio.gather(self.client.playlist(playlist_id),
                                           self.client.playlist_tracks(playlist_id))
        self._tracks(tracks)
        return n.playlist_detail(raw, tracks)

    # --- discovery ----------------------------------------------------------------
    async def trending(self, language: str, limit: int) -> list[Track]:
        """For a language: its most played songs (see `LANGUAGES`). Otherwise trending
        this week, in the genre `language` names (all genres otherwise)."""
        if lang := language_for(language):
            return await self._language_tracks(LANGUAGES[lang], limit)
        return self._tracks(await self.client.trending(limit, genre=genre_for(language)))

    async def _language_tracks(self, spec: LanguageSearch, limit: int) -> list[Track]:
        batches = await asyncio.gather(*[
            self.client.search_tracks(q, LANGUAGE_SEARCH_SIZE, sort="popular") for q in spec.queries
        ])
        rows = {r["id"]: r for r in chain.from_iterable(batches)
                if isinstance(r, dict) and r.get("id") and spec.matches(r)}
        ranked = sorted(rows.values(), key=lambda r: r.get("play_count") or 0, reverse=True)
        return [t for t in self._tracks(ranked) if t.playable][:limit]

    async def new_releases(self, language: str, limit: int) -> NewReleases:
        # Audius has no "new releases" feed: underground trending (newer, smaller artists)
        # and the top albums stand in, titled as such on Home (`section_titles`).
        tracks, albums = await asyncio.gather(self.client.trending_underground(limit),
                                              self.client.top_albums(min(limit, 20)))
        return NewReleases(language=language, tracks=self._tracks(tracks),
                           albums=[n.album_summary(r) for r in albums])

    async def charts(self, limit: int) -> list[PlaylistSummary]:
        return [n.playlist_summary(r) for r in await self.client.trending_playlists(limit)]
