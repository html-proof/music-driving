import 'package:dio/dio.dart';

import '../core/errors/app_exception.dart';
import '../core/networking/api_client.dart';
import '../core/storage/local_cache.dart';
import '../models/catalog.dart';
import '../models/track.dart';

/// Catalogue access. Everything comes from the backend, which proxies the music provider.
class MusicRepository {
  MusicRepository(this.api, this.cache, {DateTime Function()? clock}) : _now = clock ?? DateTime.now;

  final ApiClient api;
  final LocalCache cache;
  final DateTime Function() _now;

  static const _homeKey = 'home';
  static const searchCacheSize = 30;
  static const searchCacheTtl = Duration(minutes: 5);

  /// Recent search pages, least recently used first (a LinkedHashMap keeps insertion order).
  final _searchCache = <String, ({DateTime at, SearchResults results})>{};

  /// The last Home feed that had something in it, saved on this device; null when there is
  /// none (or it can't be read any more).
  Future<HomeFeed?> cachedHome() async {
    try {
      final cached = await cache.read(_homeKey);
      if (cached == null) return null;
      final feed = HomeFeed.fromJson(cached['data'] as Map<String, dynamic>, fromCache: true);
      return feed.sections.isEmpty ? null : feed;
    } catch (_) {
      return null; // a corrupt or outdated cache entry is not an error worth showing
    }
  }

  /// A fresh Home feed from the backend. It is saved for offline use only when it parsed
  /// and has at least one section, so a feed emptied by a provider outage never replaces
  /// the last good copy.
  Future<HomeFeed> home() async {
    final json = await api.get<Map<String, dynamic>>('/home');
    final HomeFeed feed;
    try {
      feed = HomeFeed.fromJson(json);
    } catch (e) {
      throw AppException('Home couldn\'t be read ($e).');
    }
    if (feed.sections.isNotEmpty) await cache.write(_homeKey, json);
    return feed;
  }

  /// One page of search results for [type] (`all`, `songs`, `albums`, `artists` or
  /// `playlists`). Pages without provider errors are kept in memory for a few minutes,
  /// so switching tabs or coming back to a query doesn't ask the provider again.
  Future<SearchResults> search(
    String q, {
    String type = 'all',
    int page = 1,
    int limit = 20,
    CancelToken? cancelToken,
  }) async {
    final key = '$q|$type|$page|$limit';
    final hit = _searchCache.remove(key);
    if (hit != null && _now().difference(hit.at) < searchCacheTtl) {
      _searchCache[key] = hit; // most recently used again
      return hit.results;
    }
    final results = SearchResults.fromJson(await api.get(
      '/search',
      query: {'q': q, 'type': type, 'page': page, 'limit': limit, 'save': false},
      cancelToken: cancelToken,
    ));
    if (results.errors.isEmpty) {
      _searchCache[key] = (at: _now(), results: results);
      while (_searchCache.length > searchCacheSize) {
        _searchCache.remove(_searchCache.keys.first);
      }
    }
    return results;
  }

  /// Adds [q] to the user's recent searches without running it again. Best effort: a
  /// failure here must never interrupt what the user tapped.
  Future<void> recordSearch(String q) async {
    try {
      await api.post<dynamic>('/library/search-history', data: {'query': q});
    } catch (_) {}
  }

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
