import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:melodia/core/errors/app_exception.dart';
import 'package:melodia/features/home/home_screen.dart';
import 'package:melodia/features/player/audio_handler.dart';
import 'package:melodia/features/player/play_queue.dart';
import 'package:melodia/features/session/session_controller.dart';
import 'package:melodia/models/catalog.dart';
import 'package:melodia/models/user.dart';
import 'package:melodia/providers/core_providers.dart';

import 'audio_handler_test.dart' show FakeEngine, FakeReporter, MemoryStore;
import 'fakes.dart';

HomeFeed feed(List<HomeSection> sections, {Map<String, String> errors = const {}, String greeting = 'Good evening'}) =>
    HomeFeed(greeting: greeting, sections: sections, errors: errors);

HomeSection section(String id, String title, String songTitle, {bool stale = false}) =>
    HomeSection(id: id, title: title, type: 'tracks', tracks: [fakeTrack('$id-1', title: songTitle)], stale: stale);

class NamedSession extends SessionController {
  @override
  SessionState build() => const SessionState(
        SessionStatus.ready,
        user: AppUser(id: 'u1', displayName: 'Seb', preferences: UserPreferences()),
      );
}

void main() {
  late FakeMusicRepository repo;
  late MelodiaAudioHandler handler;

  setUp(() {
    repo = FakeMusicRepository();
    handler = RecordingHandler();
  });

  Future<void> pumpHome(WidgetTester tester) async {
    await tester.pumpWidget(ProviderScope(
      overrides: [
        musicRepositoryProvider.overrideWithValue(repo),
        audioHandlerProvider.overrideWithValue(handler),
        sessionProvider.overrideWith(ReadySession.new),
      ],
      child: const MaterialApp(home: HomeScreen()),
    ));
    await tester.pump(); // microtask: cache read
    await tester.pump();
  }

  testWidgets('the saved feed shows at once while the fresh one loads', (tester) async {
    repo.savedHome = feed([section('trending_hindi', 'Trending in Hindi', 'Saved song')]);
    final fresh = Completer<HomeFeed>();
    repo.onHome = () => fresh.future;
    await pumpHome(tester);
    expect(find.text('Saved song'), findsOneWidget);
    expect(find.byType(LinearProgressIndicator), findsOneWidget);
    expect(find.text('Offline · showing saved Home'), findsNothing); // refresh hasn't failed

    fresh.complete(feed([section('trending_hindi', 'Trending in Hindi', 'Fresh song')]));
    await tester.pump();
    expect(find.text('Fresh song'), findsOneWidget);
    expect(find.text('Saved song'), findsNothing);
  });

  testWidgets('a failed refresh keeps the saved feed and says it is offline', (tester) async {
    repo.savedHome = feed([section('trending_hindi', 'Trending in Hindi', 'Saved song')]);
    repo.onHome = () async => throw const AppException('Can\'t reach the server.', isNetwork: true);
    await pumpHome(tester);
    expect(find.text('Saved song'), findsOneWidget);
    expect(find.text('Offline · showing saved Home'), findsOneWidget);
    expect(repo.homeCalls, 1); // no automatic retries
    await tester.pump(const Duration(seconds: 10));
    expect(repo.homeCalls, 1);
  });

  testWidgets('an empty fresh feed does not replace the saved one', (tester) async {
    repo.savedHome = feed([section('trending_hindi', 'Trending in Hindi', 'Saved song')]);
    repo.onHome = () async => feed([], errors: {'trending_hindi': 'Music provider is currently unavailable'});
    await pumpHome(tester);
    expect(find.text('Saved song'), findsOneWidget);
    expect(find.text('Offline · showing saved Home'), findsOneWidget);
  });

  testWidgets('first load without a saved feed shows skeletons, then the feed', (tester) async {
    final fresh = Completer<HomeFeed>();
    repo.onHome = () => fresh.future;
    await pumpHome(tester);
    expect(find.byKey(const ValueKey('home-skeleton')), findsOneWidget);
    fresh.complete(feed([section('charts', 'Top charts', 'Chart song')], greeting: 'Good morning'));
    await tester.pump();
    await tester.pump();
    expect(find.byKey(const ValueKey('home-skeleton')), findsNothing);
    expect(find.text('Chart song'), findsOneWidget);
    expect(find.text(localGreeting()), findsOneWidget); // device time, not the server's
  });

  testWidgets('the greeting names the user once, in the device\'s time of day', (tester) async {
    repo.onHome = () async => feed([section('charts', 'Top charts', 'Chart song')], greeting: 'Good evening, Seb');
    await tester.pumpWidget(ProviderScope(
      overrides: [
        musicRepositoryProvider.overrideWithValue(repo),
        audioHandlerProvider.overrideWithValue(handler),
        sessionProvider.overrideWith(NamedSession.new),
      ],
      child: const MaterialApp(home: HomeScreen()),
    ));
    await tester.pump();
    await tester.pump();
    expect(find.text('Chart song'), findsOneWidget);
    expect(find.text('${localGreeting()}, Seb'), findsOneWidget);
    expect(find.textContaining('Seb, Seb'), findsNothing);
  });

  test('localGreeting follows the given clock', () {
    expect(localGreeting(DateTime(2026, 1, 1, 9)), 'Good morning');
    expect(localGreeting(DateTime(2026, 1, 1, 15)), 'Good afternoon');
    expect(localGreeting(DateTime(2026, 1, 1, 21)), 'Good evening');
  });

  testWidgets('stale sections are marked and failed sections are listed with a retry', (tester) async {
    var calls = 0;
    repo.onHome = () async {
      calls++;
      return feed([
        section('trending_malayalam', 'Trending in Malayalam', 'Old song', stale: true),
        section('international_hits', 'International hits', 'New song'),
      ], errors: {'new_albums_tamil': 'Music provider is currently unavailable'});
    };
    await pumpHome(tester);
    expect(find.text('saved copy'), findsOneWidget); // only on the stale section
    expect(find.text('Couldn\'t load: New albums (Tamil)'), findsOneWidget);
    await tester.tap(find.widgetWithText(TextButton, 'Retry'));
    await tester.pump();
    expect(calls, 2);
  });

  testWidgets('Continue listening resumes the restored song', (tester) async {
    final engine = FakeEngine();
    final store = MemoryStore()
      ..data = {
        'queue': PlayQueue(items: [fakeTrack('kesariya', title: 'Kesariya')]).toJson(),
        'position_ms': 42000,
      };
    handler = MelodiaAudioHandler(
      engine: engine,
      resolveStream: (id, q) async => StreamInfo(url: 'https://cdn/$id.m3u8', quality: q, bitrateKbps: 128),
      reporter: FakeReporter(),
      store: store,
      configureSession: false,
    );
    await tester.runAsync(handler.init);
    repo.onHome = () async => feed([section('charts', 'Top charts', 'Chart song')]);
    await pumpHome(tester);
    await tester.pump();
    expect(find.text('Continue listening'), findsOneWidget);
    expect(find.text('Kesariya'), findsOneWidget);

    await tester.runAsync(() async {
      await tester.tap(find.text('Kesariya'));
      await Future<void>.delayed(const Duration(milliseconds: 20));
    });
    expect(engine.playing, isTrue);
    expect(engine.position, const Duration(seconds: 42));
  });

  test('reloading Home (e.g. new languages) keeps the current feed while it refreshes', () async {
    final container = ProviderContainer(overrides: [
      musicRepositoryProvider.overrideWithValue(repo),
      audioHandlerProvider.overrideWithValue(handler),
      sessionProvider.overrideWith(ReadySession.new),
    ]);
    addTearDown(container.dispose);
    repo.onHome = () async => feed([section('trending_hindi', 'Trending in Hindi', 'Hindi song')]);
    container.listen(homeFeedProvider, (_, _) {});
    await pumpEventQueue();
    expect(container.read(homeFeedProvider).feed!.sections.single.id, 'trending_hindi');

    final next = Completer<HomeFeed>();
    repo.onHome = () => next.future;
    container.invalidate(homeFeedProvider);
    final reloading = container.read(homeFeedProvider);
    expect(reloading.refreshing, isTrue);
    expect(reloading.feed!.sections.single.id, 'trending_hindi');

    next.complete(feed([section('trending_malayalam', 'Trending in Malayalam', 'Malayalam song')]));
    await pumpEventQueue();
    final done = container.read(homeFeedProvider);
    expect(done.refreshing, isFalse);
    expect(done.feed!.sections.single.id, 'trending_malayalam');
  });

  test('section ids get readable names', () {
    expect(homeSectionLabel('trending_malayalam'), 'Trending in Malayalam');
    expect(homeSectionLabel('top_artists'), 'Popular artists');
    expect(homeSectionLabel('something_new'), 'Something new');
  });
}
