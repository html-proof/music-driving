import asyncio

from api.entities import artist_row_from_entity, page_slice, search_items
from api.errors import UpstreamError, most_severe


class Artists:
    async def search_artists(self, search_query: str, limit: int, page: int = 1) -> list:
        """Rows built straight from the search hits: one Gaana request, no detail lookups."""
        endpoints = self.api_endpoints
        errors = self.errors
        result = await self._safe_request(
            "POST", endpoints.search_url, params=endpoints.search_params("artist", search_query)
        )
        if isinstance(result, dict) and "error" in result:
            return result
        rows = []
        seen = set()
        for item in search_items(result):
            row = artist_row_from_entity(item)
            if row is not None and row["seokey"] not in seen:
                seen.add(row["seokey"])
                rows.append(row)
        rows = page_slice(rows, limit, page)
        if len(rows) == 0:
            return await errors.no_results()
        return rows

    async def get_artist_info(self, artist_id: list, info: bool, limit: int = 10, page: int = 1) -> list:
        """One artistDetail request per artist. A failed artist is dropped; when all of
        them failed, the most severe failure (a block first) is raised."""
        endpoints = self.api_endpoints
        errors = self.errors
        results = await asyncio.gather(*[
            self._safe_request("POST", endpoints.artist_details_url + i)
            for i in artist_id
        ], return_exceptions=True)
        artist_info = []
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
            artist = await self.format_json_artists(result, limit, page, info=info)
            if "error" not in artist:
                artist_info.append(artist)
        if len(artist_info) == 0:
            if failures:
                raise most_severe(failures)
            return await errors.no_results()
        return artist_info

    async def get_top_tracks(self, artist_id: str, limit: int = 10, page: int = 1) -> dict:
        """The artist's tracks, one page of them, built from the track-list payload
        (songDetail only for entries that lack title or artwork)."""
        endpoints = self.api_endpoints
        result = await self._safe_request("POST", endpoints.artist_top_tracks + str(artist_id))
        if isinstance(result, dict) and "error" in result:
            return {"tracks": [], "total": 0}
        entities = [
            entity for entity in result.get('entities') or []
            if isinstance(entity, dict) and entity.get('seokey')
        ]
        total = len(entities)
        tracks = await self.songs_from_entities(page_slice(entities, limit, page), limit)
        return {"tracks": tracks, "total": total}

    async def get_similar_artists(self, artist_id: str, limit: int) -> dict:
        endpoints = self.api_endpoints
        errors = self.errors
        result = await self._safe_request("GET", endpoints.similar_artists_url + artist_id)
        if isinstance(result, dict) and "error" in result:
            return result
        entities = []
        entities_list = result.get('entities', [])
        for i in range(min(limit, len(entities_list))):
            entities.append(entities_list[i])
        if len(entities) == 0:
            return await errors.no_results()
        similar_artists = []
        similar_artists.extend(await asyncio.gather(*[self.format_json_similar_artists(entity) for entity in entities]))
        return similar_artists

    async def format_json_artists(self, results: dict, limit: int = 10, page: int = 1, info: bool = False) -> dict:
        errors = self.errors
        data = {}

        artist_list = results.get('artist')
        if not artist_list or not isinstance(artist_list, list) or len(artist_list) == 0:
            return await errors.invalid_seokey()
        artist = artist_list[0]

        seokey = artist.get('seokey')
        if not seokey:
            return await errors.invalid_seokey()

        data['seokey'] = seokey
        data['artist_id'] = artist.get('artist_id', '')
        data['name'] = artist.get('name', '')
        data['song_count'] = artist.get('songs', '')
        data['album_count'] = artist.get('albums', '')
        data['favorite_count'] = artist.get('favorite_count', '')
        data['artist_url'] = f"https://gaana.com/artist/{data['seokey']}"
        atw = artist.get('atw', '')
        data['images'] = {'urls': {}}
        data['images']['urls']['large_artwork'] = atw.replace("size_m", "size_l") if atw else ''
        data['images']['urls']['medium_artwork'] = atw
        data['images']['urls']['small_artwork'] = atw.replace("size_m", "size_s") if atw else ''
        if info:
            top_tracks_data = await self.get_top_tracks(data['artist_id'], limit, page)
            data['top_tracks'] = top_tracks_data.get('tracks', [])
            data['total_tracks'] = top_tracks_data.get('total', 0)
        return data

    async def format_json_similar_artists(self, results: dict) -> dict:
        errors = self.errors
        data = {}

        seokey = results.get('seokey')
        if not seokey:
            return await errors.invalid_seokey()

        data['seokey'] = seokey
        data['artist_id'] = results.get('entity_id', '')
        data['name'] = results.get('name', '')
        entity_info = results.get('entity_info') or []
        data['song_count'] = entity_info[1].get('value', '') if len(entity_info) > 1 else ''
        data['album_count'] = entity_info[0].get('value', '') if len(entity_info) > 0 else ''
        data['favorite_count'] = results.get('favorite_count', '')
        data['artist_url'] = f"https://gaana.com/artist/{data['seokey']}"
        atw = results.get('atw', '')
        data['images'] = {'urls': {}}
        data['images']['urls']['large_artwork'] = atw.replace("size_m", "size_l") if atw else ''
        data['images']['urls']['medium_artwork'] = atw
        data['images']['urls']['small_artwork'] = atw.replace("size_m", "size_s") if atw else ''
        return data
