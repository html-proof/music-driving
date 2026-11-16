import 'package:dio/dio.dart';

import '../core/errors/app_exception.dart';
import '../core/networking/api_client.dart';
import '../core/storage/local_cache.dart';
import '../models/catalog.dart';
import '../models/track.dart';

/// Catalogue access. Everything comes from the backend, which proxies the music provider.
class MusicRepository {
  MusicRepository(this.api, this.cache);

  final ApiClient api;
  final LocalCache cache;

  Future<HomeFeed> home() async {
    try {
      final json = await api.get<Map<String, dynamic>>('/home');
      await cache.write('home', json);
      return HomeFeed.fromJson(json);
    } on AppException catch (e) {
      if (!e.isNetwork && e.statusCode != 503) rethrow;
      final cached = await cache.read('home');
      if (cached == null) rethrow;
      return HomeFeed.fromJson(cached['data'] as Map<String, dynamic>, fromCache: true);
    }
  }

  Future<SearchResults> search(String q, {CancelToken? cancelToken, bool save = false}) async =>
      SearchResults.fromJson(await api.get('/search', query: {'q': q, 'limit': 10, 'save': save}, cancelToken: cancelToken));

  Future<Track> song(String id) async => Track.fromJson(await api.get('/songs/$id'));

  Future<AlbumDetail> album(String id) async => AlbumDetail.fromJson(await api.get('/albums/$id'));

  Future<ArtistDetail> artist(String id) async => ArtistDetail.fromJson(await api.get('/artists/$id', query: {'limit': 10}));

  Future<({List<Track> items, bool hasMore})> artistTracks(String numericId, int page) async {
    final j = await api.get<Map<String, dynamic>>('/artists/$numericId/tracks', query: {'page': page, 'limit': 20});
    return (items: tracksFrom(j['items']), hasMore: j['has_more'] as bool? ?? false);
  }

  Future<PlaylistDetail> playlist(String id) async => PlaylistDetail.fromJson(await api.get('/playlists/$id'));

  Future<StreamInfo> stream(String songId, String quality) async =>
      StreamInfo.fromJson(await api.get('/playback/stream/$songId', query: {'quality': quality}));

  Future<Lyrics> lyrics(String songId) async => Lyrics.fromJson(await api.get('/lyrics/$songId'));

  Future<List<Map<String, dynamic>>> searchHistory() async =>
      (await api.get<List<dynamic>>('/library/search-history')).cast<Map<String, dynamic>>();

  Future<void> clearSearchHistory() => api.delete('/library/search-history');
}
