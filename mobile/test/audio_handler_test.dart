import 'dart:async';

import 'package:audio_service/audio_service.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:melodia/core/errors/app_exception.dart';
import 'package:melodia/features/player/audio_engine.dart';
import 'package:melodia/features/player/audio_handler.dart';
import 'package:melodia/models/catalog.dart';
import 'package:melodia/models/track.dart';

/// In-memory stand-in for just_audio so the real handler logic runs in tests.
class FakeEngine implements AudioEngine {
  final _pos = StreamController<Duration>.broadcast();
  final _playing = StreamController<bool>.broadcast();
  final _state = StreamController<EngineState>.broadcast();
  final _dur = StreamController<Duration?>.broadcast();
  final _err = StreamController<Object>.broadcast();
  final loadedUrls = <String>[];
  final failUrls = <String>{};

  @override
  Duration position = Duration.zero;
  @override
  bool playing = false;
  @override
  EngineState state = EngineState.idle;
  @override
  Duration? duration;
  @override
  Duration get bufferedPosition => position;

  @override
  Stream<Duration> get positionStream => _pos.stream;
  @override
  Stream<Duration> get bufferedPositionStream => _pos.stream;
  @override
  Stream<Duration?> get durationStream => _dur.stream;
  @override
  Stream<bool> get playingStream => _playing.stream;
  @override
  Stream<EngineState> get stateStream => _state.stream;
  @override
  Stream<Object> get errorStream => _err.stream;

  @override
  Future<Duration?> setUrl(String url, {Duration? initialPosition}) async {
    if (failUrls.contains(url)) throw Exception('Source error');
    loadedUrls.add(url);
    position = initialPosition ?? Duration.zero;
    state = EngineState.ready;
    _state.add(state);
    duration = const Duration(minutes: 3);
    _dur.add(duration);
    return duration;
  }

  @override
  Future<void> play() async {
    playing = true;
    _playing.add(true);
  }

  @override
  Future<void> pause() async {
    playing = false;
    _playing.add(false);
  }

  @override
  Future<void> seek(Duration p) async => position = p;

  @override
  Future<void> stop() async {
    playing = false;
    state = EngineState.idle;
    _state.add(state);
  }

  double volume = 1.0;
  @override
  double speed = 1.0;

  @override
  Future<void> setVolume(double v) async => volume = v;
  @override
  Future<void> setSpeed(double s) async => speed = s;

  @override
  Future<void> dispose() async {}

  /// Simulate playback advancing in 1 s steps (feeds the listened-time counter).
  void advance(Duration by) {
    final end = position + by;
    while (position < end) {
      position += const Duration(seconds: 1);
      _pos.add(position);
    }
  }

  void finish() {
    state = EngineState.completed;
    _state.add(state);
  }

  void emitError(Object e) => _err.add(e);
}

class FakeReporter implements PlaybackReporter {
  final completes = <(String, bool)>[];
  int syncs = 0;
  @override
  Future<void> complete(String songId, double secondsListened, {required bool completed, String? context}) async =>
      completes.add((songId, completed));
  @override
  Future<void> progress(String songId, double positionSeconds, int index) async {}
  @override
  Future<void> syncSession({
    required List<String> queue,
    required int currentIndex,
    required double positionSeconds,
    required bool shuffle,
    required String repeatMode,
    required String quality,
    String? context,
  }) async =>
      syncs++;
}

class MemoryStore implements QueueStore {
  Map<String, dynamic>? data;
  @override
  Future<Map<String, dynamic>?> load() async => data;
  @override
  Future<void> save(Map<String, dynamic> state) async => data = state;
}

List<Track> tracks(int n) => List.generate(n, (i) => Track(id: 's$i', title: 'Song $i', duration: 180));

void main() {
  late FakeEngine engine;
  late FakeReporter reporter;
  late MemoryStore store;
  late MelodiaAudioHandler handler;
  late List<String> resolved;
  late Set<String> unavailable;
  late DateTime Function() expiry;

  Future<StreamInfo> resolve(String id, String quality) async {
    resolved.add('$id@$quality');
    if (unavailable.contains(id)) throw const AppException('No stream', statusCode: 404);
    return StreamInfo(url: 'https://cdn/$id/$quality.m3u8?n=${resolved.length}', quality: quality, bitrateKbps: 128,
        expiresAt: expiry());
  }

  setUp(() {
    engine = FakeEngine();
    reporter = FakeReporter();
    store = MemoryStore();
    resolved = [];
    unavailable = {};
    expiry = () => DateTime.now().toUtc().add(const Duration(hours: 4));
    handler = MelodiaAudioHandler(
      engine: engine,
      resolveStream: resolve,
      reporter: reporter,
      store: store,
      configureSession: false,
    );
  });

  Future<void> settle() => Future<void>.delayed(const Duration(milliseconds: 10));

  test('playTracks loads the chosen song and starts playing', () async {
    await handler.playTracks(tracks(3), startIndex: 1, context: 'album:X');
    expect(handler.currentTrack!.id, 's1');
    expect(engine.loadedUrls.single, startsWith('https://cdn/s1/high'));
    expect(engine.playing, isTrue);
    expect(handler.mediaItem.value!.title, 'Song 1');
    expect(handler.queue.value.length, 3);
    expect(handler.playbackState.value.queueIndex, 1);
  });

  test('previous within 3 s goes back; after 3 s restarts', () async {
    await handler.playTracks(tracks(3), startIndex: 1);
    engine.advance(const Duration(seconds: 2));
    await handler.skipToPrevious();
    expect(handler.currentTrack!.id, 's0');

    engine.advance(const Duration(seconds: 10));
    await handler.skipToPrevious(); // first song, >3 s: restart
    expect(handler.currentTrack!.id, 's0');
    expect(engine.position, Duration.zero);

    await handler.skipToNext();
    engine.advance(const Duration(seconds: 5));
    await handler.skipToPrevious(); // >3 s: restart, stay on s1
    expect(handler.currentTrack!.id, 's1');
    expect(engine.position, Duration.zero);
  });

  test('previous on the first song with nothing before it restarts', () async {
    await handler.playTracks(tracks(2));
    engine.advance(const Duration(seconds: 1));
    await handler.skipToPrevious();
    expect(handler.currentTrack!.id, 's0');
    expect(engine.position, Duration.zero);
  });

  test('completion auto-advances and records a completed listen', () async {
    await handler.playTracks(tracks(2));
    engine.advance(const Duration(seconds: 30));
    engine.finish();
    await settle();
    expect(handler.currentTrack!.id, 's1');
    expect(engine.playing, isTrue);
    expect(reporter.completes, [('s0', true)]);
  });

  test('skipping reports an incomplete listen', () async {
    await handler.playTracks(tracks(2));
    engine.advance(const Duration(seconds: 12));
    await settle(); // position events are delivered asynchronously
    await handler.skipToNext();
    expect(reporter.completes, [('s0', false)]);
  });

  test('end of queue rewinds to the first song, paused', () async {
    await handler.playTracks(tracks(2), startIndex: 1);
    engine.finish();
    await settle();
    expect(handler.currentTrack!.id, 's0');
    expect(engine.playing, isFalse);
  });

  test('repeat one replays the same song', () async {
    await handler.playTracks(tracks(2));
    await handler.setRepeatMode(AudioServiceRepeatMode.one);
    engine.advance(const Duration(seconds: 5));
    engine.finish();
    await settle();
    expect(handler.currentTrack!.id, 's0');
    expect(engine.position, Duration.zero);
    expect(engine.playing, isTrue);
  });

  test('an unplayable song is skipped without breaking the queue', () async {
    unavailable.add('s1');
    final errors = <String>[];
    handler.errors.listen(errors.add);
    await handler.playTracks(tracks(3), startIndex: 1);
    await settle();
    expect(handler.currentTrack!.id, 's2');
    expect(engine.playing, isTrue);
    expect(errors.single, contains('Song 1'));
  });

  test('when every song fails playback stops with an error instead of looping', () async {
    unavailable.addAll({'s0', 's1'});
    final errors = <String>[];
    handler.errors.listen(errors.add);
    await handler.playTracks(tracks(2));
    await settle();
    expect(engine.playing, isFalse);
    expect(errors, isNotEmpty);
  });

  test('an expired stream URL is refreshed before resuming', () async {
    // The provider token expires within the 2-minute safety margin, i.e. it is stale.
    expiry = () => DateTime.now().toUtc().add(const Duration(minutes: 1));
    await handler.playTracks(tracks(1));
    engine.advance(const Duration(seconds: 40));
    await handler.pause();
    expiry = () => DateTime.now().toUtc().add(const Duration(hours: 4));
    final before = resolved.length;
    final urlsBefore = engine.loadedUrls.length;
    await handler.play();
    expect(resolved.length, before + 1); // fetched a fresh URL
    expect(engine.loadedUrls.length, urlsBefore + 1);
    expect(engine.position, const Duration(seconds: 40)); // resumed where it was
    expect(engine.playing, isTrue);
  });

  test('a still-valid URL resumes without another request', () async {
    await handler.playTracks(tracks(1));
    await handler.pause();
    final before = resolved.length;
    await handler.play();
    expect(resolved.length, before);
    expect(engine.playing, isTrue);
  });

  test('mid-stream errors re-resolve the URL and resume at the same position', () async {
    await handler.playTracks(tracks(2));
    engine.advance(const Duration(seconds: 50));
    final before = resolved.length;
    engine.emitError(Exception('403 token expired'));
    await settle();
    expect(resolved.length, greaterThan(before));
    expect(handler.currentTrack!.id, 's0');
    expect(engine.position, const Duration(seconds: 50));
  });

  test('changing quality reloads the current song at the same position', () async {
    await handler.playTracks(tracks(1));
    engine.advance(const Duration(seconds: 20));
    await handler.setQuality('very_high');
    expect(engine.loadedUrls.last, contains('/very_high.m3u8'));
    expect(engine.position, const Duration(seconds: 20));
  });

  test('shuffle keeps the current song and publishes the new order', () async {
    await handler.playTracks(tracks(6), startIndex: 3);
    await handler.setShuffleMode(AudioServiceShuffleMode.all);
    expect(handler.currentTrack!.id, 's3');
    expect(handler.queue.value.first.id, 's3');
    expect(handler.playbackState.value.shuffleMode, AudioServiceShuffleMode.all);
  });

  test('queue state survives a restart without touching the network', () async {
    await handler.playTracks(tracks(3), startIndex: 2);
    engine.advance(const Duration(seconds: 42));
    await handler.pause();
    await Future<void>.delayed(const Duration(milliseconds: 600)); // persist debounce
    expect(store.data, isNotNull);

    final engine2 = FakeEngine();
    final restored = MelodiaAudioHandler(
      engine: engine2,
      resolveStream: resolve,
      reporter: reporter,
      store: store,
      configureSession: false,
    );
    final resolvedBefore = resolved.length;
    await restored.init();
    expect(restored.currentTrack!.id, 's2');
    expect(restored.displayPosition, const Duration(seconds: 42));
    expect(resolved.length, resolvedBefore); // lazy: nothing resolved yet
    await restored.play();
    expect(engine2.position, const Duration(seconds: 42));
    expect(engine2.playing, isTrue);
  });

  test('notification/lock-screen controls are published', () async {
    await handler.playTracks(tracks(2));
    final s = handler.playbackState.value;
    expect(s.controls.map((c) => c.action), [MediaAction.skipToPrevious, MediaAction.pause, MediaAction.skipToNext]);
    expect(s.systemActions, contains(MediaAction.seek));
    expect(s.androidCompactActionIndices, [0, 1, 2]);
  });
}
