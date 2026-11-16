trending_url = "https://gaana.com/apiv2?type=miscTrendingSongs"
song_details_url = "https://gaana.com/apiv2?type=songDetail&seokey="
#similar_songs_url = "https://gaana.com/apiv2?type=songSimilar&id=" ## Removed for now as the endpoint seems to return nothing
#similar_albums_url = "https://gaana.com/apiv2?type=albumSimilar&id="
similar_artists_url = "https://apiv2.gaana.com/player/similar-artists/" ## Mobile-specific endpoint
playlist_details_url = "https://gaana.com/apiv2?type=playlistDetail&seokey="
new_releases_url = "https://gaana.com/apiv2?page=0&type=miscNewRelease&language="
charts_url = "https://apiv2.gaana.com/home/playlist/top-charts?view=all&limit=0,"
artist_details_url = "https://gaana.com/apiv2?type=artistDetail&seokey="
artist_top_tracks = "https://gaana.com/apiv2?language=&order=0&page=0&sortBy=popularity&type=artistTrackList&id="
album_details_url = "https://gaana.com/apiv2?type=albumDetail&seokey="
similar_albums_url = "https://rec.gaana.com/recommendation/similarAlbums/"
artist_tracks_url = "https://apiv2.gaana.com/home/artist/tracks/"

# Search: the keyword goes in as a query parameter (URL-encoded by aiohttp), never
# concatenated, so any script and characters like "&" reach Gaana intact.
search_url = "https://gaana.com/apiv2"


def search_params(sec_type: str, keyword: str) -> dict:
    """Query parameters of Gaana's search; sec_type is track, album or artist."""
    return {
        "country": "IN",
        "page": "0",
        "secType": sec_type,
        "type": "search",
        "keyword": keyword,
    }
