import 'package:dio/dio.dart';
import 'package:melodia/core/networking/api_client.dart';
import 'package:melodia/core/storage/local_cache.dart';
import 'package:melodia/core/storage/token_storage.dart';
import 'package:melodia/features/player/audio_handler.dart';
import 'package:melodia/features/session/session_controller.dart';
import 'package:melodia/models/catalog.dart';
import 'package:melodia/models/track.dart';
import 'package:melodia/services/music_repository.dart';

import 'audio_handler_test.dart' show FakeEngine, FakeReporter, MemoryStore;

typedef SearchCall = ({String q, String type, int page});

/// Catalogue repository with scripted answers; nothing reaches the network.
class FakeMusicRepository extends MusicRepository {
  FakeMusicRepository() : super(ApiClient(tokens: TokenStorage(), dio: Dio()), MemoryLocalCache());

  final searchCalls = <SearchCall>[];
  final recorded = <String>[];
  Future<SearchResults> Function(SearchCall call)? onSearch;

  HomeFeed? savedHome;
  Future<HomeFeed> Function()? onHome;
  int homeCalls = 0;

  @override
  Future<SearchResults> search(String q, {String type = 'all', int page = 1, int limit = 20, CancelToken? cancelToken}) {
    final call = (q: q, type: type, page: page);
    searchCalls.add(call);
    return onSearch!(call);
  }

  @override
  Future<void> recordSearch(String q) async => recorded.add(q);

  @override
  Future<List<Map<String, dynamic>>> searchHistory() async => const [];

  @override
  Future<HomeFeed?> cachedHome() async => savedHome;

  @override
  Future<HomeFeed> home() {
    homeCalls++;
    return onHome!();
  }
}

/// Records what the UI asked to play instead of playing it.
class RecordingHandler extends MelodiaAudioHandler {
  RecordingHandler()
      : super(
          engine: FakeEngine(),
          resolveStream: (id, q) async => StreamInfo(url: 'https://cdn/$id.m3u8', quality: q, bitrateKbps: 128),
          reporter: FakeReporter(),
          store: MemoryStore(),
          configureSession: false,
        );

  final played = <({List<String> ids, int startIndex, String? context})>[];

  @override
  Future<void> playTracks(List<Track> tracks, {int startIndex = 0, String? context, bool? shuffle}) async =>
      played.add((ids: tracks.map((t) => t.id).toList(), startIndex: startIndex, context: context));
}

/// A ready session without touching the backend.
class ReadySession extends SessionController {
  @override
  SessionState build() => const SessionState(SessionStatus.ready);
}

Track fakeTrack(String id, {String? title, int duration = 0}) =>
    Track(id: id, title: title ?? 'Song $id', artists: const [ArtistRef(name: 'Arijit Singh', id: 'arijit-singh')], duration: duration);
