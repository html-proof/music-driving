import asyncio

from api.entities import album_row_from_entity
from api.errors import UpstreamError, most_severe


class NewReleases:
    async def get_new_releases(self, language: str, limit: int) -> dict:
        """{"tracks": [...], "albums": [...]}, up to `limit` of EACH type.

        Rows come from the new-releases payload itself; details are only looked up for
        entries that lack title or artwork. One failed type leaves the other intact.
        """
        endpoints = self.api_endpoints
        errors = self.errors
        result = await self._safe_request("POST", endpoints.new_releases_url + language)
        if isinstance(result, dict) and "error" in result:
            return result
        track_entities = []
        album_entities = []
        for entity in result.get('entities') or []:
            if not isinstance(entity, dict) or not entity.get('seokey'):
                continue
            etype = entity.get('entity_type')
            if etype == "AL":
                album_entities.append(entity)
            elif etype == "TR":
                track_entities.append(entity)
        if len(track_entities) == 0 and len(album_entities) == 0:
            return await errors.no_results()
        tracks, albums = await asyncio.gather(
            self.songs_from_entities(track_entities, limit),
            self._albums_from_entities(album_entities, limit),
            return_exceptions=True,
        )
        failures = [part for part in (tracks, albums) if isinstance(part, BaseException)]
        for failure in failures:
            # Only provider failures are tolerated; a bug must surface as one.
            if not isinstance(failure, UpstreamError):
                raise failure
        usable = [part for part in (tracks, albums) if isinstance(part, list) and part]
        if failures and not usable:
            raise most_severe(failures)
        data = {}
        data['tracks'] = tracks if isinstance(tracks, list) else []
        data['albums'] = albums if isinstance(albums, list) else []
        if not data['tracks'] and not data['albums']:
            return await errors.no_results()
        return data

    async def _albums_from_entities(self, entities: list, limit: int) -> list:
        """Album rows for the first `limit` album entities; albumDetail only for the
        entries that lack title or artwork."""
        rows = []
        for entity in entities[:limit]:
            rows.append(album_row_from_entity(entity) or entity['seokey'])
        pending = [row for row in rows if isinstance(row, str)]
        details = {}
        if pending:
            try:
                found = await self.get_album_info(pending, False)
            except UpstreamError:
                if not any(isinstance(row, dict) for row in rows):
                    raise
                found = []
            if isinstance(found, list):
                for album in found:
                    details.setdefault(album.get('seokey'), album)
        out = []
        for row in rows:
            row = details.get(row) if isinstance(row, str) else row
            if row is not None:
                out.append(row)
        return out
