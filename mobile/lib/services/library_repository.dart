import '../core/errors/app_exception.dart';
import '../core/networking/api_client.dart';
import '../core/storage/local_cache.dart';
import '../models/catalog.dart';
import '../models/track.dart';
import '../models/user.dart';

/// User library with offline fallback: the last successful response is cached in SQLite.
class LibraryRepository {
  LibraryRepository(this.api, this.cache);

  final ApiClient api;
  final LocalCache cache;

  Future<T> _cached<T>(String key, Future<dynamic> Function() fetch, T Function(dynamic) decode) async {
    try {
      final json = await fetch();
      await cache.write(key, json as Object);
      return decode(json);
    } on AppException catch (e) {
      if (!e.isNetwork) rethrow;
      final cached = await cache.read(key);
      if (cached == null) rethrow;
      return decode(cached['data']);
    }
  }

  Future<List<Track>> likedSongs() => _cached(
        'liked',
        () => api.get('/library/liked', query: {'limit': 200}),
        (j) => (j['items'] as List).map((e) => Track.fromJson(e['track'] as Map<String, dynamic>)).toList(),
      );

  Future<void> like(String songId) => api.post('/library/liked/$songId');
  Future<void> unlike(String songId) => api.delete('/library/liked/$songId');

  Future<List<UserPlaylist>> playlists() => _cached(
        'playlists',
        () => api.get('/library/playlists'),
        (j) => (j as List).map((e) => UserPlaylist.fromJson(e as Map<String, dynamic>)).toList(),
      );

  Future<UserPlaylist> playlist(String id) => _cached(
        'playlist:$id',
        () => api.get('/library/playlists/$id'),
        (j) => UserPlaylist.fromJson(j as Map<String, dynamic>),
      );

  Future<UserPlaylist> createPlaylist(String name, {String? description}) async =>
      UserPlaylist.fromJson(await api.post('/playlists', data: {'name': name, 'description': description}));

  Future<UserPlaylist> updatePlaylist(String id, {String? name, String? description}) async =>
      UserPlaylist.fromJson(await api.put('/playlists/$id', data: {'name': ?name, 'description': ?description}));

  Future<void> deletePlaylist(String id) => api.delete('/playlists/$id');

  /// Returns (added, alreadyPresent, failed) song ids.
  Future<({List<String> added, List<String> already, Map<String, String> failed})> addToPlaylist(
      String playlistId, List<String> songIds) async {
    final j = await api.post<Map<String, dynamic>>('/playlists/$playlistId/songs', data: {'song_ids': songIds});
    return (
      added: (j['added'] as List).cast<String>(),
      already: (j['already_present'] as List).cast<String>(),
      failed: (j['failed'] as Map).cast<String, String>(),
    );
  }

  Future<UserPlaylist> removeFromPlaylist(String playlistId, String songId) async =>
      UserPlaylist.fromJson(await api.delete('/playlists/$playlistId/songs/$songId'));

  Future<UserPlaylist> reorderPlaylist(String playlistId, List<String> songIds) async =>
      UserPlaylist.fromJson(await api.put('/playlists/$playlistId/order', data: {'song_ids': songIds}));

  Future<List<ArtistSummary>> followedArtists() => _cached(
        'followed',
        () => api.get('/library/followed-artists'),
        (j) => (j as List).map((e) => ArtistSummary.fromJson(e['artist'] as Map<String, dynamic>)).toList(),
      );

  Future<void> follow(String artistId) => api.post('/library/followed-artists/$artistId');
  Future<void> unfollow(String artistId) => api.delete('/library/followed-artists/$artistId');

  Future<List<Track>> recentlyPlayed() => _cached(
        'recent',
        () => api.get('/library/recently-played', query: {'limit': 30}),
        (j) => tracksFrom(j),
      );

  Future<Recommendations> recommendations() async => Recommendations.fromJson(await api.get('/recommendations'));
}
