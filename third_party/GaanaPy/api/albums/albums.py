import asyncio

from api.entities import album_row_from_entity, artwork_urls, page_slice, search_items
from api.errors import UpstreamError, most_severe

# Album tracks without title/artwork in albumDetail are looked up one by one; cap that.
ALBUM_TRACK_LOOKUP_LIMIT = 100


class Albums:
    async def search_albums(self, search_query: str, limit: int, page: int = 1) -> list:
        """Rows built straight from the search hits: one Gaana request, no detail lookups."""
        endpoints = self.api_endpoints
        errors = self.errors
        result = await self._safe_request(
            "POST", endpoints.search_url, params=endpoints.search_params("album", search_query)
        )
        if isinstance(result, dict) and "error" in result:
            return result
        rows = []
        seen = set()
        for item in search_items(result):
            row = album_row_from_entity(item, require_artwork=False)
            if row is not None and row["seokey"] not in seen:
                seen.add(row["seokey"])
                rows.append(row)
        rows = page_slice(rows, limit, page)
        if len(rows) == 0:
            return await errors.no_results()
        return rows

    async def get_album_info(self, album_id: list, info: bool) -> list:
        """One albumDetail request per album. A failed album is dropped; when all of them
        failed, the most severe failure (a block first) is raised."""
        endpoints = self.api_endpoints
        errors = self.errors
        results = await asyncio.gather(*[
            self._safe_request("POST", endpoints.album_details_url + i)
            for i in album_id
        ], return_exceptions=True)
        album_info = []
        failures = []
        for result in results:
            if isinstance(result, BaseException):
                # Only provider failures are tolerated; a bug must surface as one.
                if not isinstance(result, UpstreamError):
                    raise result
                failures.append(result)
                continue
            if isinstance(result, dict) and "error" in result:
                continue
            album = await self.format_json_albums(result, info=info)
            if "error" not in album:
                album_info.append(album)
        if len(album_info) == 0:
            if failures:
                raise most_severe(failures)
            return await errors.no_results()
        return album_info

    async def get_album_tracks(self, results: dict) -> list:
        """Song rows for the tracks of an albumDetail payload (no second albumDetail call)."""
        tracks = results.get('tracks') if isinstance(results, dict) else None
        if not isinstance(tracks, list) or not tracks:
            return []
        return await self.songs_from_entities(tracks, ALBUM_TRACK_LOOKUP_LIMIT)

    async def format_json_albums(self, results: dict, info: bool = False) -> dict:
        functions = self.functions
        errors = self.errors
        data = {}

        album = results.get('album')
        if not album or not album.get('seokey'):
            return await errors.no_results()

        data['seokey'] = album['seokey']
        data['album_id'] = album.get('album_id', '')
        data['title'] = album.get('title', '')
        try:
            album_artist = album.get('artist') or []
            data['artists'] = await functions.findArtistNames(album_artist)
            # The album's own artist list gives keys that match the names above. Only
            # when it has none, borrow the first track's - and only if that track is
            # credited to exactly the same artists, so names and keys still pair up.
            data['artist_seokeys'] = await functions.findArtistSeoKeys(album_artist)
            data['artist_ids'] = await functions.findArtistIds(album_artist)
            if not data['artist_seokeys']:
                tracks = results.get('tracks')
                first_track_artist = (
                    tracks[0].get('artist') or []
                    if tracks and isinstance(tracks, list) and isinstance(tracks[0], dict)
                    else []
                )
                if first_track_artist and await functions.findArtistNames(first_track_artist) == data['artists']:
                    data['artist_seokeys'] = await functions.findArtistSeoKeys(first_track_artist)
                    data['artist_ids'] = await functions.findArtistIds(first_track_artist)
        except (KeyError, IndexError, AttributeError):
            data['artists'] = ""
            data['artist_seokeys'] = ""
            data['artist_ids'] = ""
        data['duration'] = album.get('duration', '')
        data['is_explicit'] = await functions.isExplicit(
            album.get('parental_warning', 0)
        )
        data['language'] = album.get('language', '')
        data['label'] = album.get('recordlevel', '')
        data['track_count'] = album.get('trackcount', '')
        data['release_date'] = album.get('release_date', '')
        data['play_count'] = album.get('al_play_ct', '')
        data['favorite_count'] = album.get('favorite_count', '')
        data['album_url'] = f"https://gaana.com/album/{data['seokey']}"
        artwork = album.get('artwork') or ''
        sizes = artwork_urls(artwork)
        data['images'] = {'urls': {}}
        data['images']['urls']['large_artwork'] = sizes['large_artwork']
        data['images']['urls']['medium_artwork'] = sizes['medium_artwork']
        data['images']['urls']['small_artwork'] = sizes['small_artwork']

        if info:
            data['tracks'] = await self.get_album_tracks(results)
        return data
