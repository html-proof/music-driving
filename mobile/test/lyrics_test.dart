import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:melodia/features/lyrics/lyrics_view.dart';
import 'package:melodia/features/player/audio_handler.dart';
import 'package:melodia/models/catalog.dart';
import 'package:melodia/models/track.dart';
import 'package:melodia/providers/core_providers.dart';

import 'audio_handler_test.dart' show FakeEngine;
import 'widgets_test.dart' show makeHandler, pumpFrames;

const song = Track(id: 'a', title: 'First Song', artists: [ArtistRef(name: 'Artist A')], duration: 180);

Lyrics synced({String songId = 'a'}) => Lyrics.fromJson({
      'song_id': songId,
      'available': true,
      'synced': true,
      'source': 'lrclib',
      // Deliberately out of order: the parser must sort.
      'lines': [
        {'time_ms': 20100, 'text': 'Third lyric line'},
        {'time_ms': 12200, 'text': 'First lyric line'},
        {'time_ms': 16400, 'text': 'Second lyric line'},
        {'time_ms': 24800, 'text': 'Fourth lyric line'},
      ],
    });

Widget panel(MelodiaAudioHandler handler, Future<Lyrics> Function() load) => ProviderScope(
      retry: (_, _) => null, // Riverpod retries failures by default; show the error state now
      overrides: [
        audioHandlerProvider.overrideWithValue(handler),
        lyricsProvider(song.id).overrideWith((ref) => load()),
      ],
      child: const MaterialApp(home: Scaffold(body: LyricsPanel(track: song))),
    );

Color? colorOf(WidgetTester tester, String text) {
  final style = tester.widget<AnimatedDefaultTextStyle>(
    find.ancestor(of: find.text(text), matching: find.byType(AnimatedDefaultTextStyle)).first,
  );
  return style.style.color;
}

void main() {
  group('Lyrics model', () {
    test('lines are sorted and the active line follows the position', () {
      final l = synced();
      expect(l.lines.map((e) => e.text).first, 'First lyric line');
      expect(l.lineIndexAt(const Duration(seconds: 5)), -1); // before the first line
      expect(l.lineIndexAt(const Duration(milliseconds: 12200)), 0);
      expect(l.lineIndexAt(const Duration(milliseconds: 16399)), 0);
      expect(l.lineIndexAt(const Duration(milliseconds: 16400)), 1);
      expect(l.lineIndexAt(const Duration(seconds: 22)), 2);
      expect(l.lineIndexAt(const Duration(minutes: 3)), 3);
    });

    test('lyrics matched to another song are rejected', () {
      expect(synced().belongsTo('a'), isTrue);
      expect(synced(songId: 'b').belongsTo('a'), isFalse);
    });
  });

  group('LyricsPanel', () {
    late FakeEngine engine;
    late MelodiaAudioHandler handler;

    setUp(() {
      engine = FakeEngine();
      handler = makeHandler(engine);
    });

    testWidgets('highlights the line at the real playback position and follows seeks', (tester) async {
      await tester.runAsync(() => handler.playTracks([song]));
      await tester.pumpWidget(panel(handler, () async => synced()));
      await pumpFrames(tester);

      // 0:00 — nothing sung yet: every line dimmed.
      expect(colorOf(tester, 'First lyric line'), isNot(Colors.white));

      await tester.runAsync(() => handler.seek(const Duration(milliseconds: 17000)));
      await pumpFrames(tester);
      expect(colorOf(tester, 'Second lyric line'), Colors.white);
      expect(colorOf(tester, 'First lyric line'), Colors.white54); // past
      expect(colorOf(tester, 'Third lyric line'), Colors.white30); // upcoming

      // Seeking backwards moves the highlight back immediately.
      await tester.runAsync(() => handler.seek(const Duration(milliseconds: 12500)));
      await pumpFrames(tester);
      expect(colorOf(tester, 'First lyric line'), Colors.white);
      expect(colorOf(tester, 'Second lyric line'), Colors.white30);

      // Seeking forward past the last timestamp.
      await tester.runAsync(() => handler.seek(const Duration(seconds: 60)));
      await pumpFrames(tester);
      expect(colorOf(tester, 'Fourth lyric line'), Colors.white);
    });

    testWidgets('tapping a line seeks the shared handler to its timestamp', (tester) async {
      await tester.runAsync(() => handler.playTracks([song]));
      await tester.pumpWidget(panel(handler, () async => synced()));
      await pumpFrames(tester);
      await tester.runAsync(() async {
        await tester.tap(find.text('Third lyric line'));
        await Future<void>.delayed(const Duration(milliseconds: 20));
      });
      await pumpFrames(tester);
      expect(engine.position, const Duration(milliseconds: 20100));
    });

    testWidgets('lyrics for a different song are never shown', (tester) async {
      await tester.pumpWidget(panel(handler, () async => synced(songId: 'other')));
      await pumpFrames(tester);
      expect(find.text('First lyric line'), findsNothing);
      expect(find.text(lyricsUnavailableMessage), findsOneWidget);
    });

    testWidgets('missing lyrics show the unavailable message', (tester) async {
      await tester.pumpWidget(panel(handler, () async => const Lyrics(available: false, synced: false, songId: 'a')));
      await pumpFrames(tester);
      expect(find.text('Lyrics are currently unavailable.'), findsOneWidget);
    });

    testWidgets('a provider failure shows the unavailable message with retry', (tester) async {
      await tester.pumpWidget(panel(handler, () async => throw Exception('down')));
      await pumpFrames(tester);
      expect(find.text(lyricsUnavailableMessage), findsOneWidget);
      expect(find.text('Try again'), findsOneWidget);
    });

    testWidgets('instrumental tracks say so', (tester) async {
      await tester.pumpWidget(panel(
          handler, () async => const Lyrics(available: false, synced: false, instrumental: true, songId: 'a')));
      await pumpFrames(tester);
      expect(find.text('This track is instrumental.'), findsOneWidget);
    });

    testWidgets('plain lyrics are labelled as not time-synced and never highlighted', (tester) async {
      await tester.pumpWidget(panel(
          handler, () async => const Lyrics(available: true, synced: false, plainText: 'Line one\nLine two', songId: 'a')));
      await pumpFrames(tester);
      expect(find.text('These lyrics aren\'t time-synced.'), findsOneWidget);
      expect(find.textContaining('Line one'), findsOneWidget);
      expect(find.byType(SyncedLyricsView), findsNothing);
    });

    testWidgets('changing track reloads lyrics for the new song', (tester) async {
      const other = Track(id: 'b', title: 'Second Song', duration: 200);
      final container = ProviderContainer(overrides: [
        audioHandlerProvider.overrideWithValue(handler),
        lyricsProvider('a').overrideWith((ref) async => synced()),
        lyricsProvider('b').overrideWith((ref) async => const Lyrics(available: false, synced: false, songId: 'b')),
      ]);
      addTearDown(container.dispose);
      Widget build(Track t) => UncontrolledProviderScope(
            container: container,
            child: MaterialApp(home: Scaffold(body: LyricsPanel(track: t))),
          );
      await tester.pumpWidget(build(song));
      await pumpFrames(tester);
      expect(find.text('First lyric line'), findsOneWidget);
      await tester.pumpWidget(build(other));
      await pumpFrames(tester);
      expect(find.text('First lyric line'), findsNothing);
      expect(find.text(lyricsUnavailableMessage), findsOneWidget);
    });
  });
}
