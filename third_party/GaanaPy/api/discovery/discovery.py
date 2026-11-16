import asyncio



class Discovery:
    """Methods for Gaana's newer discovery endpoints."""

    async def get_similar_albums(self, album_id: str, limit: int) -> list:
        result = await self._safe_request(
            "GET", self.api_endpoints.similar_albums_url + album_id,
            headers=self._gaana_headers(),
        )
        if isinstance(result, dict) and "error" in result:
            return result
        records = self._entity_records(result)
        if not records:
            return await self.errors.no_results()
        albums = await asyncio.gather(*[
            self.format_discovered_album(record) for record in records[:limit]
        ])
        albums = [album for album in albums if "error" not in album]
        return albums or await self.errors.no_results()

    async def get_artist_tracks(self, artist_id: str, limit: int, page: int) -> dict:
        result = await self._safe_request(
            "GET",
            self.api_endpoints.artist_tracks_url + artist_id,
            params={
                "sortBy": "popularity", "sortOrder": 0, "request_type": "web",
                "pkc": "true", "st": "hls", "song_type": "new",
                "limit": f"{(page - 1) * limit},{limit}",
            },
            headers=self._gaana_headers(),
        )
        if isinstance(result, dict) and "error" in result:
            return result
        records = self._track_records(result)
        if not records:
            return await self.errors.no_results()
        # The records already carry title, artwork, artists, album and the stream link:
        # build the rows from them; songDetail only for records that lack those.
        tracks = await self.songs_from_entities(records, limit)
        if not tracks:
            return await self.errors.no_results()
        return {"tracks": tracks, "total": result.get("total", len(records))}

    async def format_discovered_album(self, record: dict) -> dict:
        if "album" in record:
            return await self.format_json_albums(record)
        album = record.get("entity") if isinstance(record.get("entity"), dict) else record
        return await self.format_json_albums({"album": {
            "seokey": album.get("seokey") or album.get("seo"),
            "album_id": album.get("album_id") or album.get("entity_id", ""),
            "title": album.get("title") or album.get("name", ""),
            "artist": album.get("artist") or [],
            "duration": album.get("duration", ""),
            "language": album.get("language", ""),
            "recordlevel": album.get("recordlevel", ""),
            "trackcount": album.get("trackcount", ""),
            "release_date": album.get("release_date", ""),
            "al_play_ct": album.get("al_play_ct", ""),
            "favorite_count": album.get("favorite_count", ""),
            "artwork": album.get("artwork") or album.get("atw", ""),
        }})

    @staticmethod
    def _gaana_headers() -> dict:
        return {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36",
            "Accept": "application/json",
            "Origin": "https://gaana.com",
            "Referer": "https://gaana.com/",
            "gaanaAppVersion": "gaanaAndroid-8.60.2",
            "deviceId": "website",
            "deviceType": "GaanaWapApp",
        }

    @staticmethod
    def _entity_records(result: dict) -> list:
        if not isinstance(result, dict):
            return []
        return result.get("entities") or result.get("album") or result.get("albums") or result.get("data") or []

    @staticmethod
    def _track_records(result: dict) -> list:
        if not isinstance(result, dict):
            return []
        return result.get("tracks") or result.get("entities") or result.get("data") or []

    @staticmethod
    def _is_seokey_only(record: dict) -> bool:
        return set(record) <= {"seokey", "seo"} and bool(record.get("seokey") or record.get("seo"))
