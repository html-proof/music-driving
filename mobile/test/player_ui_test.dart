import 'package:audio_service/audio_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:melodia/features/player/audio_handler.dart';
import 'package:melodia/features/player/player_providers.dart';
import 'package:melodia/features/player/widgets/player_controls.dart';
import 'package:melodia/providers/core_providers.dart';

import 'audio_handler_test.dart' show FakeEngine, FakeReporter, MemoryStore;
import 'package:melodia/models/catalog.dart';
import 'widgets_test.dart' show makeHandler, pumpFrames, songs;

Widget controls(MelodiaAudioHandler h) => ProviderScope(
      overrides: [audioHandlerProvider.overrideWithValue(h)],
      child: const MaterialApp(home: Scaffold(body: Center(child: PlayerControls()))),
    );

Future<void> tapAndSettle(WidgetTester tester, Finder f) async {
  await tester.runAsync(() async {
    await tester.tap(f);
    await Future<void>.delayed(const Duration(milliseconds: 20));
  });
  await pumpFrames(tester);
}

void main() {
  group('playerStatusOf', () {
    PlaybackState s(AudioProcessingState p, {bool playing = false}) =>
        PlaybackState(processingState: p, playing: playing);

    test('maps every processing state to a user-facing state', () {
      expect(playerStatusOf(null), PlayerStatus.idle);
      expect(playerStatusOf(s(AudioProcessingState.idle)), PlayerStatus.idle);
      expect(playerStatusOf(s(AudioProcessingState.loading)), PlayerStatus.loading);
      expect(playerStatusOf(s(AudioProcessingState.buffering, playing: true)), PlayerStatus.buffering);
      expect(playerStatusOf(s(AudioProcessingState.ready, playing: true)), PlayerStatus.playing);
      expect(playerStatusOf(s(AudioProcessingState.ready)), PlayerStatus.paused);
      expect(playerStatusOf(s(AudioProcessingState.completed)), PlayerStatus.completed);
      expect(playerStatusOf(s(AudioProcessingState.error)), PlayerStatus.error);
    });
  });

  group('PlayerControls (same handler as notification/lock screen)', () {
    late FakeEngine engine;
    late MelodiaAudioHandler handler;

    setUp(() {
      engine = FakeEngine();
      handler = makeHandler(engine);
    });

    testWidgets('Previous at 0:10 restarts; at 0:01 plays the previous song', (tester) async {
      await tester.runAsync(() => handler.playTracks(songs, startIndex: 1));
      await tester.pumpWidget(controls(handler));
      await pumpFrames(tester);

      engine.position = const Duration(seconds: 10);
      await tapAndSettle(tester, find.byTooltip('Previous'));
      expect(handler.currentTrack!.id, 'b');
      expect(engine.position, Duration.zero);

      engine.position = const Duration(seconds: 1);
      await tapAndSettle(tester, find.byTooltip('Previous'));
      expect(handler.currentTrack!.id, 'a');
      expect(engine.position, Duration.zero);
      expect(engine.playing, isTrue);
    });

    testWidgets('Next plays the next song from 0:00 and updates the media item', (tester) async {
      await tester.runAsync(() => handler.playTracks(songs));
      await tester.pumpWidget(controls(handler));
      await pumpFrames(tester);
      engine.position = const Duration(seconds: 42);
      await tapAndSettle(tester, find.byTooltip('Next'));
      expect(handler.currentTrack!.id, 'b');
      expect(engine.position, Duration.zero);
      expect(handler.mediaItem.value!.title, 'Second Song');
      expect(handler.mediaItem.value!.artist, 'Artist B');
    });

    testWidgets('repeat cycles off → all → one → off and shuffle toggles', (tester) async {
      await tester.runAsync(() => handler.playTracks(songs));
      await tester.pumpWidget(controls(handler));
      await pumpFrames(tester);

      await tapAndSettle(tester, find.byTooltip('Repeat off'));
      expect(handler.playbackState.value.repeatMode, AudioServiceRepeatMode.all);
      await tapAndSettle(tester, find.byTooltip('Repeat all'));
      expect(handler.playbackState.value.repeatMode, AudioServiceRepeatMode.one);
      await tapAndSettle(tester, find.byTooltip('Repeat one'));
      expect(handler.playbackState.value.repeatMode, AudioServiceRepeatMode.none);

      await tapAndSettle(tester, find.byTooltip('Shuffle off'));
      expect(handler.playbackState.value.shuffleMode, AudioServiceShuffleMode.all);
      expect(find.byTooltip('Shuffle on'), findsOneWidget);
    });

    testWidgets('Play/Pause button reflects and drives the engine', (tester) async {
      await tester.runAsync(() => handler.playTracks(songs));
      await tester.pumpWidget(controls(handler));
      await pumpFrames(tester);
      expect(find.byTooltip('Pause'), findsOneWidget);
      await tapAndSettle(tester, find.byTooltip('Pause'));
      expect(engine.playing, isFalse);
      expect(find.byTooltip('Play'), findsOneWidget);
      await tapAndSettle(tester, find.byTooltip('Play'));
      expect(engine.playing, isTrue);
    });
  });

  test('Next with repeat-one on the last song wraps and keeps playing', () async {
    final engine = FakeEngine();
    final handler = makeHandler(engine);
    await handler.playTracks(songs, startIndex: 1);
    await handler.setRepeatMode(AudioServiceRepeatMode.one);
    await handler.skipToNext();
    expect(handler.currentTrack!.id, 'a');
    expect(engine.playing, isTrue);
  });

  test('Previous with an empty queue does nothing and does not throw', () async {
    final handler = makeHandler(FakeEngine());
    await handler.skipToPrevious();
    await handler.skipToNext();
    expect(handler.currentTrack, isNull);
  });

  test('setSpeed is clamped and published', () async {
    final engine = FakeEngine();
    final handler = makeHandler(engine);
    await handler.playTracks(songs);
    await handler.setSpeed(5);
    expect(engine.speed, 2.0);
    expect(handler.playbackState.value.speed, 2.0);
  });

  test('audio quality is saved on the device and restored on the next launch', () async {
    final store = MemoryStore();
    MelodiaAudioHandler make() => MelodiaAudioHandler(
          engine: FakeEngine(),
          resolveStream: (id, q) async => StreamInfo(
              url: 'https://cdn/$id/$q.m3u8', quality: q, bitrateKbps: 128,
              expiresAt: DateTime.now().toUtc().add(const Duration(hours: 4))),
          reporter: FakeReporter(),
          store: store,
          configureSession: false,
        );
    final first = make();
    await first.playTracks(songs);
    await first.setQuality('very_high');
    await Future<void>.delayed(const Duration(milliseconds: 600)); // persist debounce
    final second = make();
    await second.init();
    expect(second.quality, 'very_high');
  });
}
