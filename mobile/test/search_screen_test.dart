import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:melodia/core/config/app_config.dart';
import 'package:melodia/features/search/search_screen.dart';
import 'package:melodia/models/catalog.dart';
import 'package:melodia/models/track.dart';
import 'package:melodia/providers/core_providers.dart';

import 'fakes.dart';

SearchResults results(String type,
        {List<Track> songs = const [],
        List<ArtistSummary> artists = const [],
        int page = 1,
        Map<String, bool> hasMore = const {},
        Map<String, String> errors = const {},
        String? altQuery}) =>
    SearchResults(
        type: type, page: page, songs: songs, artists: artists, hasMore: hasMore, errors: errors, altQuery: altQuery);

void main() {
  late FakeMusicRepository repo;
  late RecordingHandler handler;

  setUp(() {
    repo = FakeMusicRepository();
    handler = RecordingHandler();
  });

  Future<void> pumpSearch(WidgetTester tester) => tester.pumpWidget(ProviderScope(
        overrides: [
          musicRepositoryProvider.overrideWithValue(repo),
          audioHandlerProvider.overrideWithValue(handler),
        ],
        child: const MaterialApp(home: SearchScreen()),
      ));

  Future<void> type(WidgetTester tester, String text) async {
    await tester.enterText(find.byType(TextField), text);
    await tester.pump(AppConfig.searchDebounce + const Duration(milliseconds: 50));
    await tester.pump();
  }

  test('queries need two Latin characters or one of another script', () {
    expect(isSearchableQuery('a'), isFalse);
    expect(isSearchableQuery('ab'), isTrue);
    expect(isSearchableQuery('മ'), isTrue);
    expect(isSearchableQuery('愛'), isTrue);
    expect(cleanSearchQuery('  tum   hi\tho '), 'tum hi ho');
  });

  testWidgets('one Latin letter does not search; one Malayalam letter does', (tester) async {
    repo.onSearch = (c) async => results(c.type, songs: [fakeTrack('malare', title: 'Malare')]);
    await pumpSearch(tester);
    await type(tester, 'm');
    expect(repo.searchCalls, isEmpty);
    await type(tester, 'മ');
    expect(repo.searchCalls.single.q, 'മ');
    expect(find.text('Malare'), findsOneWidget);
  });

  testWidgets('category chips switch the searched type', (tester) async {
    repo.onSearch = (c) async => c.type == 'all'
        ? results('all',
            songs: [fakeTrack('tum-hi-ho', title: 'Tum Hi Ho')],
            artists: const [ArtistSummary(id: 'arijit-singh', name: 'Arijit Singh')])
        : results(c.type, artists: const [ArtistSummary(id: 'arijit-singh', name: 'Arijit Singh')]);
    await pumpSearch(tester);
    await type(tester, 'tum hi ho');
    expect(repo.searchCalls.single, (q: 'tum hi ho', type: 'all', page: 1));
    for (final label in ['All', 'Songs', 'Artists', 'Albums', 'Playlists']) {
      expect(find.widgetWithText(ChoiceChip, label), findsOneWidget);
    }
    expect(find.text('Podcasts'), findsNothing);
    expect(find.text('Tum Hi Ho'), findsOneWidget);

    await tester.tap(find.byKey(const ValueKey('search-tab-artists')));
    await tester.pump();
    expect(repo.searchCalls.last, (q: 'tum hi ho', type: 'artists', page: 1));
    expect(find.text('Tum Hi Ho'), findsNothing); // only the artists section now
    expect(find.text('Arijit Singh'), findsOneWidget);
  });

  testWidgets('a slow earlier response never replaces a newer one', (tester) async {
    final pending = <String, Completer<SearchResults>>{};
    repo.onSearch = (c) => (pending[c.q] = Completer<SearchResults>()).future;
    await pumpSearch(tester);
    await type(tester, 'malar');
    await type(tester, 'malare');
    expect(repo.searchCalls.map((c) => c.q), ['malar', 'malare']);

    pending['malare']!.complete(results('all', songs: [fakeTrack('new', title: 'Newer result')]));
    await tester.pump();
    pending['malar']!.complete(results('all', songs: [fakeTrack('old', title: 'Stale result')]));
    await tester.pump();
    expect(find.text('Newer result'), findsOneWidget);
    expect(find.text('Stale result'), findsNothing);
  });

  testWidgets('submitting cancels the pending debounce (one search, not two)', (tester) async {
    repo.onSearch = (c) async => results('all', songs: [fakeTrack('a')]);
    await pumpSearch(tester);
    await tester.enterText(find.byType(TextField), 'butta bomma');
    await tester.testTextInput.receiveAction(TextInputAction.search);
    await tester.pump(AppConfig.searchDebounce * 2);
    expect(repo.searchCalls, hasLength(1));
  });

  testWidgets('tapping a song plays the visible list and records history without searching again',
      (tester) async {
    final songs = [for (var i = 0; i < 3; i++) fakeTrack('song-$i', title: 'Track $i', duration: i == 0 ? 0 : 245)];
    repo.onSearch = (c) async => results('all', songs: songs, altQuery: 'malare');
    await pumpSearch(tester);
    await type(tester, 'മലരേ');
    expect(find.text('Showing results for "malare" too'), findsOneWidget);
    expect(find.text('Song · Arijit Singh · 4:05'), findsNWidgets(2));
    expect(find.text('Song · Arijit Singh'), findsOneWidget); // unknown duration: no 0:00

    await tester.tap(find.text('Track 1'));
    await tester.pump();
    final played = handler.played.single;
    expect(played.ids, ['song-0', 'song-1', 'song-2']);
    expect(played.startIndex, 1);
    expect(played.context, 'search:മലരേ');
    expect(repo.recorded, ['മലരേ']);
    expect(repo.searchCalls, hasLength(1));
  });

  testWidgets('a failed section shows its own retry while the others still show', (tester) async {
    repo.onSearch = (c) async => results('all',
        songs: [fakeTrack('a', title: 'Visible song')], errors: {'artists': 'Music provider is currently unavailable'});
    await pumpSearch(tester);
    await type(tester, 'arijit');
    expect(find.text('Visible song'), findsOneWidget);
    expect(find.textContaining('Artists couldn\'t load'), findsOneWidget);
    await tester.tap(find.widgetWithText(TextButton, 'Retry'));
    await tester.pump();
    expect(repo.searchCalls, hasLength(2));
  });

  testWidgets('a category tab loads the next page on scroll and stops when has_more is false', (tester) async {
    repo.onSearch = (c) async {
      if (c.type == 'all') return results('all', songs: [fakeTrack('first', title: 'p1-0')], hasMore: {'songs': true});
      return c.page == 1
          ? results('songs', page: 1, songs: [for (var i = 0; i < 20; i++) fakeTrack('p1-$i', title: 'p1-$i')], hasMore: {'songs': true})
          : results('songs', page: 2, songs: [for (var i = 0; i < 5; i++) fakeTrack('p2-$i', title: 'p2-$i')], hasMore: {'songs': false});
    };
    await pumpSearch(tester);
    await type(tester, 'tum hi ho');
    await tester.tap(find.byKey(const ValueKey('see-all-songs')));
    await tester.pump();
    expect(repo.searchCalls.last, (q: 'tum hi ho', type: 'songs', page: 1));

    await tester.drag(find.text('p1-0'), const Offset(0, -2000));
    await tester.pump();
    await tester.pump();
    expect(repo.searchCalls.last, (q: 'tum hi ho', type: 'songs', page: 2));

    await tester.drag(find.byType(Scrollable).last, const Offset(0, -3000));
    await tester.pump();
    expect(find.text('p2-4'), findsOneWidget); // appended after page 1
    expect(repo.searchCalls.where((c) => c.page == 3), isEmpty);
    expect(repo.searchCalls, hasLength(3));
  });

  testWidgets('a failed next page is not re-requested by scrolling, only by "Try again"', (tester) async {
    repo.onSearch = (c) async {
      if (c.type == 'all') return results('all', songs: [fakeTrack('first', title: 'p1-0')], hasMore: {'songs': true});
      return c.page == 1
          ? results('songs', page: 1, songs: [for (var i = 0; i < 20; i++) fakeTrack('p1-$i', title: 'p1-$i')], hasMore: {'songs': true})
          : results('songs', page: 2, errors: {'songs': 'Music provider is currently unavailable'});
    };
    await pumpSearch(tester);
    await type(tester, 'tum hi ho');
    await tester.tap(find.byKey(const ValueKey('see-all-songs')));
    await tester.pump();

    await tester.drag(find.text('p1-0'), const Offset(0, -2000));
    await tester.pump();
    await tester.pump();
    int page2() => repo.searchCalls.where((c) => c.page == 2).length;
    expect(page2(), 1);
    expect(find.text('Music provider is currently unavailable'), findsOneWidget);

    // More scrolling near the bottom (drags, flings, overscroll) must not ask again.
    for (var i = 0; i < 3; i++) {
      await tester.drag(find.byType(Scrollable).last, const Offset(0, -500));
      await tester.pump();
      await tester.drag(find.byType(Scrollable).last, const Offset(0, 300));
      await tester.pump();
    }
    await tester.fling(find.byType(Scrollable).last, const Offset(0, -1500), 3000);
    await tester.pumpAndSettle();
    expect(page2(), 1);
    expect(find.text('Music provider is currently unavailable'), findsOneWidget);

    await tester.tap(find.widgetWithText(TextButton, 'Try again'));
    await tester.pump();
    await tester.pump();
    expect(page2(), 2);
  });
}
