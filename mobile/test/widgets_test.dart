import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:melodia/features/player/audio_handler.dart';
import 'package:melodia/features/player/widgets/mini_player.dart';
import 'package:melodia/features/player/widgets/seek_bar.dart';
import 'package:melodia/models/catalog.dart';
import 'package:melodia/models/track.dart';
import 'package:melodia/providers/core_providers.dart';

import 'audio_handler_test.dart' show FakeEngine, FakeReporter, MemoryStore;

MelodiaAudioHandler makeHandler(FakeEngine engine) => MelodiaAudioHandler(
      engine: engine,
      resolveStream: (id, q) async =>
          StreamInfo(url: 'https://cdn/$id.m3u8', quality: q, bitrateKbps: 128, expiresAt: DateTime.now().toUtc().add(const Duration(hours: 4))),
      reporter: FakeReporter(),
      store: MemoryStore(),
      configureSession: false,
    );

Widget wrap(MelodiaAudioHandler handler, Widget child) => ProviderScope(
      overrides: [audioHandlerProvider.overrideWithValue(handler)],
      child: MaterialApp(home: Scaffold(body: child)),
    );

const songs = [
  Track(id: 'a', title: 'First Song', artists: [ArtistRef(name: 'Artist A')], duration: 180),
  Track(id: 'b', title: 'Second Song', artists: [ArtistRef(name: 'Artist B')], duration: 200),
];

void main() {
  testWidgets('mini player is hidden until something plays, then controls the shared handler', (tester) async {
    final engine = FakeEngine();
    final handler = makeHandler(engine);
    await tester.pumpWidget(wrap(handler, const MiniPlayer()));
    expect(find.text('First Song'), findsNothing);

    await tester.runAsync(() async {
      await handler.playTracks(songs);
      await Future<void>.delayed(const Duration(milliseconds: 20)); // let stream events flush
    });
    await pumpFrames(tester);
    expect(find.text('First Song'), findsOneWidget);
    expect(find.byTooltip('Pause'), findsOneWidget);

    await tester.runAsync(() async {
      await tester.tap(find.byTooltip('Pause'));
      await Future<void>.delayed(const Duration(milliseconds: 20));
    });
    await pumpFrames(tester);
    expect(engine.playing, isFalse);
    expect(find.byTooltip('Play'), findsOneWidget);

    await tester.runAsync(() async {
      await tester.tap(find.byTooltip('Next'));
      await Future<void>.delayed(const Duration(milliseconds: 20));
    });
    await pumpFrames(tester);
    expect(find.text('Second Song'), findsOneWidget);
  });

  testWidgets('seek bar shows elapsed/total and seeks the handler on release', (tester) async {
    final engine = FakeEngine();
    final handler = makeHandler(engine);
    await tester.runAsync(() => handler.playTracks(songs));
    await tester.pumpWidget(wrap(handler, const SeekBar()));
    await pumpFrames(tester);
    expect(find.text('0:00'), findsOneWidget);
    expect(find.text('3:00'), findsOneWidget);

    // Tap at the middle of the slider -> ~1:30.
    final slider = find.byType(Slider);
    await tester.tapAt(tester.getCenter(slider));
    await pumpFrames(tester);
    expect(engine.position.inSeconds, inInclusiveRange(80, 100));

    // Toggle total -> remaining time.
    await tester.tap(find.text('3:00'));
    await pumpFrames(tester);
    expect(find.textContaining('-1:'), findsOneWidget);
  });

}

/// Provider updates can land a frame after the stream event; pump a few frames.
Future<void> pumpFrames(WidgetTester tester) async {
  for (var i = 0; i < 4; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}
