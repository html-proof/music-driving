import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:melodia/core/errors/app_exception.dart';
import 'package:melodia/core/networking/api_client.dart';
import 'package:melodia/core/storage/local_cache.dart';
import 'package:melodia/core/storage/token_storage.dart';
import 'package:melodia/services/music_repository.dart';

/// Recorded backend answers; no network.
class FakeCatalogBackend implements HttpClientAdapter {
  final requests = <RequestOptions>[];
  Map<String, dynamic> Function(RequestOptions o)? home;
  int searchStatus = 200;
  int historyStatus = 204;
  Map<String, dynamic> searchErrors = const {};

  ResponseBody _json(int status, Object? body) => ResponseBody.fromString(body == null ? '' : jsonEncode(body), status,
      headers: {Headers.contentTypeHeader: [Headers.jsonContentType]});

  @override
  Future<ResponseBody> fetch(RequestOptions o, Stream<Uint8List>? requestStream, Future<void>? cancelFuture) async {
    requests.add(o);
    switch (o.path) {
      case '/search':
        if (searchStatus != 200) return _json(searchStatus, {'detail': 'Music provider is currently unavailable'});
        final q = o.queryParameters;
        return _json(200, {
          'query': q['q'],
          'type': q['type'],
          'page': q['page'],
          'alt_query': null,
          'songs': [
            {'id': 'tum-hi-ho-p${q['page']}', 'title': 'Tum Hi Ho', 'artists': [{'name': 'Arijit Singh'}], 'duration': 0},
          ],
          'albums': <dynamic>[],
          'artists': <dynamic>[],
          'playlists': <dynamic>[],
          'errors': searchErrors,
          'has_more': {'songs': true},
        });
      case '/library/search-history':
        return _json(historyStatus, historyStatus == 204 ? null : {'detail': 'nope'});
      case '/home':
        return _json(200, home!(o));
    }
    return _json(404, {'detail': 'Not found'});
  }

  @override
  void close({bool force = false}) {}
}

Map<String, dynamic> feedJson(List<String> sectionIds, {Map<String, String> errors = const {}}) => {
      'greeting': 'Good evening',
      'languages': ['Hindi'],
      'sections': [
        for (final id in sectionIds)
          {
            'id': id,
            'title': 'Section $id',
            'type': 'tracks',
            'tracks': [
              {'id': '$id-song', 'title': 'Song of $id', 'artists': <dynamic>[], 'duration': 200},
            ],
          },
      ],
      'errors': errors,
      'unavailable_languages': <String>[],
      'generated_at': '2026-11-16T10:00:00Z',
    };

void main() {
  late FakeCatalogBackend backend;
  late MemoryLocalCache cache;
  late DateTime now;
  late MusicRepository repo;

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    backend = FakeCatalogBackend();
    cache = MemoryLocalCache();
    now = DateTime(2026, 11, 16, 12);
    final dio = Dio(BaseOptions(baseUrl: 'http://api.test'))..httpClientAdapter = backend;
    repo = MusicRepository(ApiClient(tokens: TokenStorage(), dio: dio), cache, clock: () => now);
  });

  Iterable<RequestOptions> searches() => backend.requests.where((r) => r.path == '/search');

  group('search', () {
    test('sends query, type, page and limit, never saving history itself', () async {
      final r = await repo.search('തും ഹി ഹോ', type: 'songs', page: 2, limit: 20);
      final q = searches().single.queryParameters;
      expect(q['q'], 'തും ഹി ഹോ');
      expect(q['type'], 'songs');
      expect(q['page'], 2);
      expect(q['limit'], 20);
      expect(q['save'], false);
      expect(r.page, 2);
      expect(r.songs.single.id, 'tum-hi-ho-p2');
    });

    test('repeat searches within 5 minutes come from memory', () async {
      await repo.search('tum hi ho', type: 'songs');
      await repo.search('tum hi ho', type: 'songs');
      expect(searches(), hasLength(1));
      await repo.search('tum hi ho', type: 'albums'); // a different tab is a different entry
      expect(searches(), hasLength(2));
      now = now.add(const Duration(minutes: 6));
      await repo.search('tum hi ho', type: 'songs');
      expect(searches(), hasLength(3));
    });

    test('keeps at most 30 entries, dropping the least recently used', () async {
      for (var i = 0; i < 30; i++) {
        await repo.search('q$i');
      }
      await repo.search('q0'); // touch: now most recently used
      await repo.search('q30'); // evicts q1
      backend.requests.clear();
      await repo.search('q0');
      expect(searches(), isEmpty);
      await repo.search('q1');
      expect(searches(), hasLength(1));
    });

    test('results with provider errors are not cached, so Retry asks again', () async {
      backend.searchErrors = {'albums': 'Music provider is currently unavailable'};
      final r = await repo.search('malare');
      expect(r.errors, contains('albums'));
      await repo.search('malare');
      expect(searches(), hasLength(2));
    });
  });

  group('recordSearch', () {
    test('posts the query to search history', () async {
      await repo.recordSearch('Malare');
      final post = backend.requests.single;
      expect(post.method, 'POST');
      expect(post.path, '/library/search-history');
      expect(post.data, {'query': 'Malare'});
    });

    test('swallows failures', () async {
      backend.historyStatus = 500;
      await expectLater(repo.recordSearch('Malare'), completes);
    });
  });

  group('home', () {
    test('a feed with sections is saved and comes back as the cached feed', () async {
      backend.home = (_) => feedJson(['trending_hindi']);
      expect(await repo.cachedHome(), isNull);
      final fresh = await repo.home();
      expect(fresh.fromCache, isFalse);
      final cached = await repo.cachedHome();
      expect(cached!.fromCache, isTrue);
      expect(cached.sections.single.id, 'trending_hindi');
    });

    test('an empty feed never overwrites the last good copy', () async {
      backend.home = (_) => feedJson(['trending_hindi', 'charts']);
      await repo.home();
      backend.home = (_) => feedJson([], errors: {'trending_hindi': 'Music provider is currently unavailable'});
      final empty = await repo.home();
      expect(empty.sections, isEmpty);
      expect(empty.errors, contains('trending_hindi')); // reported, not hidden
      final cached = await repo.cachedHome();
      expect(cached!.sections.map((s) => s.id), ['trending_hindi', 'charts']);
    });

    test('a malformed feed is an error and is not saved', () async {
      backend.home = (_) => {'sections': 'oops'};
      await expectLater(repo.home(), throwsA(isA<AppException>()));
      expect(await repo.cachedHome(), isNull);
    });
  });
}
