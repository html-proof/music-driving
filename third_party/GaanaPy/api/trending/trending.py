class Trending:
    async def get_trending(self, language: str, limit: int) -> list:
        """Trending songs, built from the trending payload itself (songDetail only for
        entries that lack title or artwork)."""
        endpoints = self.api_endpoints
        errors = self.errors
        headers = {'Cookie': f'__ul={language};'}
        result = await self._safe_request("POST", endpoints.trending_url, headers=headers)
        if isinstance(result, dict) and "error" in result:
            return result
        entities = [entity for entity in result.get('entities') or [] if isinstance(entity, dict)]
        tracks = await self.songs_from_entities(entities, limit)
        if len(tracks) == 0:
            return await errors.no_results()
        return tracks
