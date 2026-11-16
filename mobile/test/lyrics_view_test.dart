import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:melodia/features/lyrics/lyrics_view.dart';
import 'package:melodia/features/player/audio_handler.dart';
import 'package:melodia/features/player/player_providers.dart';
import 'package:melodia/models/catalog.dart';
import 'package:melodia/models/track.dart';
import 'package:melodia/providers/core_providers.dart';

import 'audio_handler_test.dart' show FakeEngine, FakeReporter, MemoryStore;

const songs = [
  Track(id: 'a', title: 'First Song', artists: [ArtistRef(name: 'Artist A')], duration: 180),
  Track(id: 'b', title: 'Second Song', artists: [ArtistRef(name: 'Artist B')], duration: 200),
];

Lyrics synced(String songId, List<String> texts) => Lyrics(
      songId: songId,
      available: true,
      synced: true,
      lines: [for (var i = 0; i < texts.length; i++) LyricLine(Duration(seconds: 12 + 4 * i), texts[i])],
    );

MelodiaAudioHandler makeHandler(FakeEngine engine) => MelodiaAudioHandler(
      engine: engine,
      resolveStream: (id, q) async => StreamInfo(
          url: 'https://cdn/$id.m3u8', quality: q, bitrateKbps: 128, expiresAt: DateTime.now().toUtc().add(const Duration(hours: 4))),
      reporter: FakeReporter(),
      store: MemoryStore(),
      configureSession: false,
    );

/// Mirrors the player's lyrics mode: lyrics for whatever track is currently playing.
Widget app(MelodiaAudioHandler handler, Map<String, Lyrics> lyricsBySong) => ProviderScope(
      overrides: [
        audioHandlerProvider.overrideWithValue(handler),
        lyricsProvider.overrideWith((ref, songId) async => lyricsBySong[songId]!),
      ],
      child: MaterialApp(
        home: Scaffold(
          body: Consumer(builder: (context, ref, _) {
            final track = ref.watch(currentTrackProvider);
            return track == null ? const SizedBox() : LyricsPanel(track: track);
          }),
        ),
      ),
    );

Future<void> settleUi(WidgetTester tester) async {
  for (var i = 0; i < 6; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

Color? colorOf(WidgetTester tester, String text) => tester
    // Nearest ancestor: the lyric line's own style (Material adds more further up).
    .widget<AnimatedDefaultTextStyle>(
        find.ancestor(of: find.text(text), matching: find.byType(AnimatedDefaultTextStyle)).first)
    .style
    .color;

void main() {
  testWidgets('active lyric follows the real playback position, including seeks back and forward', (tester) async {
    final engine = FakeEngine();
    final handler = makeHandler(engine);
    await tester.pumpWidget(app(handler, {'a': synced('a', ['Line one', 'Line two', 'Line three'])}));
    await tester.runAsync(() async {
      await handler.playTracks(songs);
      await Future<void>.delayed(const Duration(milliseconds: 20));
    });
    await settleUi(tester);
    // 0:00 — before the first timestamp nothing is highlighted.
    expect(colorOf(tester, 'Line one'), isNot(Colors.white));

    await tester.runAsync(() => handler.seek(const Duration(seconds: 17))); // seek forward
    await settleUi(tester);
    expect(colorOf(tester, 'Line two'), Colors.white);
    expect(colorOf(tester, 'Line one'), isNot(Colors.white));
    expect(colorOf(tester, 'Line three'), isNot(Colors.white)); // upcoming line still visible

    await tester.runAsync(() => handler.seek(const Duration(seconds: 13))); // seek backward
    await settleUi(tester);
    expect(colorOf(tester, 'Line one'), Colors.white);
    expect(colorOf(tester, 'Line two'), isNot(Colors.white));

    await tester.runAsync(() => handler.seek(const Duration(seconds: 21)));
    await settleUi(tester);
    expect(colorOf(tester, 'Line three'), Colors.white);
  });

  testWidgets('tapping a lyric line seeks the audio there', (tester) async {
    final engine = FakeEngine();
    final handler = makeHandler(engine);
    await tester.pumpWidget(app(handler, {'a': synced('a', ['Line one', 'Line two', 'Line three'])}));
    await tester.runAsync(() async {
      await handler.playTracks(songs);
      await Future<void>.delayed(const Duration(milliseconds: 20));
    });
    await settleUi(tester);
    await tester.runAsync(() async => tester.tap(find.text('Line three')));
    await settleUi(tester);
    expect(engine.position, const Duration(seconds: 20));
    expect(colorOf(tester, 'Line three'), Colors.white);
  });

  testWidgets('changing song loads that song\'s lyrics', (tester) async {
    final engine = FakeEngine();
    final handler = makeHandler(engine);
    await tester.pumpWidget(app(handler, {
      'a': synced('a', ['A lyric']),
      'b': synced('b', ['B lyric']),
    }));
    await tester.runAsync(() async {
      await handler.playTracks(songs);
      await Future<void>.delayed(const Duration(milliseconds: 20));
    });
    await settleUi(tester);
    expect(find.text('A lyric'), findsOneWidget);

    await tester.runAsync(() async {
      await handler.skipToNext();
      await Future<void>.delayed(const Duration(milliseconds: 20));
    });
    await settleUi(tester);
    expect(find.text('B lyric'), findsOneWidget);
    expect(find.text('A lyric'), findsNothing);
  });

  testWidgets('lyrics matched to a different song are never shown', (tester) async {
    final engine = FakeEngine();
    final handler = makeHandler(engine);
    await tester.pumpWidget(app(handler, {'a': synced('other-song', ['Wrong song lyric'])}));
    await tester.runAsync(() async {
      await handler.playTracks(songs);
      await Future<void>.delayed(const Duration(milliseconds: 20));
    });
    await settleUi(tester);
    expect(find.text('Wrong song lyric'), findsNothing);
    expect(find.text(lyricsUnavailableMessage), findsOneWidget);
  });

  testWidgets('unsynced lyrics are labelled and never highlighted as live', (tester) async {
    final engine = FakeEngine();
    final handler = makeHandler(engine);
    await tester.pumpWidget(app(handler, {
      'a': const Lyrics(songId: 'a', available: true, synced: false, plainText: 'Plain words'),
    }));
    await tester.runAsync(() async {
      await handler.playTracks(songs);
      await Future<void>.delayed(const Duration(milliseconds: 20));
    });
    await settleUi(tester);
    expect(find.text('Plain words'), findsOneWidget);
    expect(find.text('These lyrics aren\'t time-synced.'), findsOneWidget);
    expect(find.byType(SyncedLyricsView), findsNothing);
  });

  testWidgets('missing and instrumental lyrics show honest messages', (tester) async {
    final engine = FakeEngine();
    final handler = makeHandler(engine);
    await tester.pumpWidget(app(handler, {
      'a': const Lyrics(songId: 'a', available: false, synced: false),
      'b': const Lyrics(songId: 'b', available: false, synced: false, instrumental: true),
    }));
    await tester.runAsync(() async {
      await handler.playTracks(songs);
      await Future<void>.delayed(const Duration(milliseconds: 20));
    });
    await settleUi(tester);
    expect(find.text(lyricsUnavailableMessage), findsOneWidget);

    await tester.runAsync(() async {
      await handler.skipToNext();
      await Future<void>.delayed(const Duration(milliseconds: 20));
    });
    await settleUi(tester);
    expect(find.text('This track is instrumental.'), findsOneWidget);
  });
}
