import pytest
from unittest.mock import AsyncMock
import re

from api.discovery.discovery import Discovery
from api.functions import Functions
from api.songs.songs import Songs
from api.errors import Errors
from api import endpoints
from app import ARTIST_ID_PATTERN


class FakeDiscovery(Discovery):
    def __init__(self, response):
        self.api_endpoints = endpoints
        self.errors = Errors()
        self._safe_request = AsyncMock(return_value=response)
        self.format_discovered_album = AsyncMock(
            return_value={"seokey": "album", "title": "Album"}
        )
        self.format_json_songs = AsyncMock(
            return_value={"seokey": "track", "stream_urls": {"urls": {"medium_quality": "url"}}}
        )


@pytest.mark.asyncio
async def test_similar_albums_are_formatted_with_required_headers():
    discovery = FakeDiscovery({"entities": [{"seokey": "album"}]})

    result = await discovery.get_similar_albums("123", 10)

    assert result == [{"seokey": "album", "title": "Album"}]
    call = discovery._safe_request.await_args
    assert call.args == ("GET", endpoints.similar_albums_url + "123")
    assert "User-Agent" in call.kwargs["headers"]


class FakeArtistTracks(Discovery, Songs):
    def __init__(self, response):
        self.api_endpoints = endpoints
        self.errors = Errors()
        self.functions = AsyncMock(spec=Functions)
        self.functions.decryptLink.return_value = "https://cdn.gaana.com/hls/64.mp4"
        self._safe_request = AsyncMock(return_value=response)


ARTIST_TRACK_RECORD = {
    "seokey": "track",
    "entity_id": "80692668",
    "name": "Song",
    "language": "Hindi",
    "artwork": "https://a10.gaanacdn.com/images/albums/1/crop_175x175_1.jpg",
    "atw": "https://a10.gaanacdn.com/gn_img/albums/x/y/size_m_1712905431.jpg",
    "entity_type": "TR",
    "entity_info": [
        {"key": "artist", "value": [{"name": "Arijit Singh", "seokey": "arijit-singh", "artist_id": 1}]},
        {"key": "album", "value": [{"album_id": "9", "album_seokey": "the-album", "name": "The Album"}]},
        {"key": "duration", "value": "261"},
        {"key": "stream_url", "value": {"medium": {"message": "encrypted"}}},
    ],
}


@pytest.mark.asyncio
async def test_artist_tracks_are_formatted_and_paginated_with_headers():
    discovery = FakeArtistTracks({"tracks": [ARTIST_TRACK_RECORD], "total": 20})

    result = await discovery.get_artist_tracks("456", 5, 2)

    track = result["tracks"][0]
    assert track["seokey"] == "track"
    assert track["track_id"] == "80692668"
    assert track["title"] == "Song"
    assert track["artists"] == "Arijit Singh"
    assert track["artist_seokeys"] == "arijit-singh"
    assert track["artist_ids"] == "1"
    assert track["album"] == "The Album" and track["album_seokey"] == "the-album"
    assert track["duration"] == "261"
    assert track["stream_urls"]["urls"]["medium_quality"] == "https://cdn.gaana.com/hls/64.mp4"
    assert result["total"] == 20
    # Built from the record itself: one Gaana request, no songDetail lookup.
    assert discovery._safe_request.await_count == 1
    call = discovery._safe_request.await_args
    assert call.kwargs["params"] == {
        "sortBy": "popularity", "sortOrder": 0, "request_type": "web",
        "pkc": "true", "st": "hls", "song_type": "new", "limit": "5,5",
    }
    assert "Origin" in call.kwargs["headers"]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,args", [
    ("get_similar_albums", ("123", 10)),
    ("get_artist_tracks", ("456", 10, 1)),
])
async def test_empty_upstream_results_use_no_results_error(method, args):
    discovery = FakeDiscovery({})

    assert await getattr(discovery, method)(*args) == {
        "error": "Unable to find any results!"
    }


@pytest.mark.asyncio
async def test_upstream_error_is_returned_unchanged():
    discovery = FakeDiscovery({"error": "Unable to find any results!"})

@pytest.mark.parametrize("value", ["", "abc", "12-3"])
def test_id_validation_pattern_rejects_non_numeric_values(value):
    assert re.fullmatch(ARTIST_ID_PATTERN, value) is None
