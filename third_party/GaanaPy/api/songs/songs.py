import asyncio

from api.entities import encrypted_stream, page_slice, search_items, song_row_from_entity
from api.errors import UpstreamError, most_severe


class Songs:
    async def search_songs(self, search_query: str, limit: int, page: int = 1) -> list:
        """Rows built straight from the search hits: one Gaana request, no detail lookups."""
        endpoints = self.api_endpoints
        errors = self.errors
        result = await self._safe_request(
            "POST", endpoints.search_url, params=endpoints.search_params("track", search_query)
        )
        if isinstance(result, dict) and "error" in result:
            return result
        rows = _unique(song_row_from_entity(item, require_artwork=False) for item in search_items(result))
        rows = page_slice(rows, limit, page)
        if len(rows) == 0:
            return await errors.no_results()
        return rows

    async def songs_from_entities(self, entities: list, limit: int) -> list:
        """Song rows for the first `limit` entities of a list payload, in order.

        Entities that carry seokey + title + artwork become rows directly; only the others
        are looked up with songDetail (at most `limit`). A failed lookup drops that row
        only; the block/outage is raised when nothing at all could be built.
        """
        rows = []
        for entity in entities if isinstance(entities, list) else []:
            if len(rows) >= limit:
                break
            row = song_row_from_entity(entity)
            if row is not None:
                message = encrypted_stream(entity)
                if message:
                    row["stream_urls"] = await self._stream_urls(message)
                rows.append(row)
                continue
            seokey = entity.get("seokey") or entity.get("seo") if isinstance(entity, dict) else None
            if isinstance(seokey, str) and seokey:
                rows.append(seokey)
        pending = [row for row in rows if isinstance(row, str)]
        details = {}
        if pending:
            details, failures = await self._track_details(pending)
            if failures and not details and not any(isinstance(row, dict) for row in rows):
                # Nothing could be built at all: report the outage instead of "no results".
                raise most_severe(failures)
        out = []
        for row in rows:
            if isinstance(row, str):
                versions = details.get(row) or []
                # songDetail can return several versions; take the one asked for.
                row = next((t for t in versions if t.get("seokey") == row), versions[0] if versions else None)
            if row is not None:
                out.append(row)
        return _unique(out)[:limit]

    async def get_track_info(self, track_id: list, fresh: bool = False) -> list:
        """Song details for each seokey, in order.

        Local fix: details are remembered (see SongCache), so the same song showing up in
        several lists costs no new request. `fresh=True` bypasses the cache (direct song
        lookups, used to renew stream links). One failed lookup only drops that song; when
        every lookup failed, the most severe failure (a block first) is raised.
        """
        details, failures = await self._track_details(track_id, fresh)
        track_info = []
        for seokey in track_id:
            track_info.extend(details.get(seokey) or [])
        if len(track_info) == 0:
            if failures:
                raise most_severe(failures)
            return await self.errors.no_results()
        return track_info

    async def _track_details(self, track_id: list, fresh: bool = False) -> tuple[dict, list]:
        """({seokey: [formatted song, ...]}, [provider failures]) for the given seokeys."""
        endpoints = self.api_endpoints
        cache = getattr(self, "song_cache", None)
        known = {} if fresh or cache is None else cache.get_many(track_id)
        missing = list(dict.fromkeys(i for i in track_id if i not in known))
        results = await asyncio.gather(*[
            self._safe_request("POST", endpoints.song_details_url + i, cache=False)
            for i in missing
        ], return_exceptions=True)
        details = dict(known)
        failures = []
        for seokey, result in zip(missing, results):
            if isinstance(result, BaseException):
                # Only provider failures are tolerated; a bug must surface as one.
                if not isinstance(result, UpstreamError):
                    raise result
                failures.append(result)
                continue
            if isinstance(result, dict) and "error" in result:
                continue
            tracks = result.get('tracks')
            if not isinstance(tracks, list) or not tracks:
                continue
            formatted = await asyncio.gather(*[self.format_json_songs(t) for t in tracks if isinstance(t, dict)])
            formatted = [t for t in formatted if "error" not in t]
            if not formatted:
                continue
            details[seokey] = formatted
            if cache is not None:
                cache.put(seokey, formatted)
        return details, failures

    async def _stream_urls(self, message: str) -> dict:
        base_url = await self.functions.decryptLink(message)
        return {'urls': {
            'very_high_quality': base_url.replace("64.mp4", "320.mp4") if base_url else "",
            'high_quality': base_url.replace("64.mp4", "128.mp4") if base_url else "",
            'medium_quality': base_url or "",
            'low_quality': base_url.replace("64.mp4", "16.mp4") if base_url else "",
        }}

    async def format_json_songs(self, results: dict) -> dict:
        functions = self.functions
        errors = self.errors
        data = {}

        seokey = results.get('seokey')
        if not seokey:
            return await errors.invalid_seokey()

        data['seokey'] = seokey
        data['album_seokey'] = results.get('albumseokey', '')
        data['track_id'] = results.get('track_id', '')
        data['title'] = results.get('track_title', '')
        data['artists'] = await functions.findArtistNames(
            results.get('artist') or []
        )
        data['artist_seokeys'] = await functions.findArtistSeoKeys(
            results.get('artist') or []
        )
        data['artist_ids'] = await functions.findArtistIds(
            results.get('artist') or []
        )
        artist_detail = results.get('artist_detail')
        data['artist_image'] = (
            artist_detail[0].get('atw', '')
            if artist_detail and isinstance(artist_detail, list) and len(artist_detail) > 0
            else ''
        )
        data['album'] = results.get('album_title', '')
        data['album_id'] = results.get('album_id', '')
        data['duration'] = results.get('duration', '')
        data['popularity'] = results.get('popularity', '')
        data['genres'] = await functions.findGenres(
            results.get('gener') or []
        )
        data['is_explicit'] = await functions.isExplicit(
            results.get('parental_warning', 0)
        )
        data['language'] = results.get('language', '')
        data['label'] = results.get('vendor_name', '')
        data['release_date'] = results.get('release_date', '')
        data['play_count'] = results.get('play_ct', '')
        data['favorite_count'] = results.get('total_favourite_count', '')
        data['song_url'] = f"https://gaana.com/song/{data['seokey']}"
        data['album_url'] = (
            f"https://gaana.com/album/{data['album_seokey']}"
            if data['album_seokey'] else ''
        )
        data['images'] = {'urls': {}}
        data['images']['urls']['large_artwork'] = results.get('artwork_large', '')
        data['images']['urls']['medium_artwork'] = results.get('artwork_web', '')
        data['images']['urls']['small_artwork'] = results.get('artwork', '')
        medium = results.get('urls') if isinstance(results.get('urls'), dict) else {}
        medium = medium.get('medium') if isinstance(medium.get('medium'), dict) else {}
        if medium.get('message'):
            data['stream_urls'] = await self._stream_urls(medium['message'])
        else:
            data['stream_urls'] = {'urls': {
                'very_high_quality': "",
                'high_quality': "",
                'medium_quality': "",
                'low_quality': "",
            }}

        return data


def _unique(rows) -> list:
    """Rows without Nones and repeated seokeys, first occurrence kept."""
    seen = set()
    out = []
    for row in rows:
        if not row or row.get("seokey") in seen:
            continue
        seen.add(row.get("seokey"))
        out.append(row)
    return out
