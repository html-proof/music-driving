DEFAULT_PLAYLIST_LIMIT = 50


class Playlists:
    async def get_playlist_info(self, playlist_id: str, limit: int = DEFAULT_PLAYLIST_LIMIT) -> list:
        """The playlist's first `limit` tracks, built from the playlist payload itself
        (songDetail only for entries that lack title or artwork)."""
        endpoints = self.api_endpoints
        errors = self.errors
        result = await self._safe_request("POST", endpoints.playlist_details_url + playlist_id)
        # Gaana now includes "error": "SUCCESS" in successful playlist payloads,
        # so only treat the response as an error when it carries no tracks.
        if not isinstance(result, dict) or not isinstance(result.get("tracks"), list) or not result["tracks"]:
            return await errors.no_results()
        tracks = result["tracks"]
        try:
            count = int(result.get('count'))
        except (TypeError, ValueError):
            count = len(tracks)
        entities = [track for track in tracks[:max(0, count)] if isinstance(track, dict)]
        track_data = await self.songs_from_entities(entities, limit)
        if len(track_data) == 0:
            return await errors.no_results()
        return track_data
