import 'package:flutter_test/flutter_test.dart';
import 'package:melodia/models/catalog.dart';
import 'package:melodia/models/track.dart';

Map<String, dynamic> song(String id, {int? duration}) => {
      'id': id,
      'title': 'Title $id',
      'artists': [
        {'name': 'Arijit Singh', 'id': null, 'numeric_id': null},
      ],
      'duration': ?duration,
      'artwork': {'small': 's.jpg', 'medium': 'm.jpg', 'large': 'l.jpg'},
      'playable': true,
    };

void main() {
  test('SearchResults reads type, page, alt_query and has_more', () {
    final r = SearchResults.fromJson({
      'query': 'മലരേ',
      'type': 'songs',
      'page': 2,
      'alt_query': 'malare',
      'songs': [song('malare', duration: 0)],
      'albums': <dynamic>[],
      'artists': <dynamic>[],
      'playlists': <dynamic>[],
      'errors': {'albums': 'Music provider is currently unavailable'},
      'has_more': {'songs': true, 'albums': false},
    });
    expect(r.query, 'മലരേ');
    expect(r.type, 'songs');
    expect(r.page, 2);
    expect(r.altQuery, 'malare');
    expect(r.songs.single.id, 'malare');
    expect(r.hasMoreFor('songs'), isTrue);
    expect(r.hasMoreFor('albums'), isFalse);
    expect(r.hasMoreFor('artists'), isFalse); // missing -> false
    expect(r.errors['albums'], contains('unavailable'));
  });

  test('SearchResults is lenient with older or partial payloads', () {
    final r = SearchResults.fromJson({'songs': [song('a')]});
    expect(r.type, 'all');
    expect(r.page, 1);
    expect(r.altQuery, isNull);
    expect(r.hasMore, isEmpty);
    expect(r.errors, isEmpty);
    expect(SearchResults.fromJson({'alt_query': '  '}).altQuery, isNull);
  });

  test('appending a page keeps source ids and drops rows already shown', () {
    final first = SearchResults.fromJson({
      'type': 'songs',
      'songs': [song('a'), song('b')],
      'has_more': {'songs': true},
    });
    final second = SearchResults.fromJson({
      'type': 'songs',
      'page': 2,
      'songs': [song('b'), song('c')],
      'has_more': {'songs': false},
    });
    final merged = first.append(second);
    expect(merged.songs.map((t) => t.id), ['a', 'b', 'c']);
    expect(merged.page, 2);
    expect(merged.hasMoreFor('songs'), isFalse);
  });

  test('a duration of 0 means unknown', () {
    final lite = Track.fromJson(song('lite', duration: 0));
    expect(lite.hasDuration, isFalse);
    expect(Track.fromJson(song('nodur')).hasDuration, isFalse);
    expect(Track.fromJson(song('full', duration: 254)).hasDuration, isTrue);
  });

  test('HomeSection reads stale; HomeFeed reads generated_at', () {
    final feed = HomeFeed.fromJson({
      'greeting': 'Good evening',
      'languages': ['Malayalam'],
      'generated_at': '2026-11-16T10:00:00Z',
      'sections': [
        {'id': 'trending_malayalam', 'title': 'Trending in Malayalam', 'type': 'tracks', 'tracks': [song('a')], 'stale': true},
        {'id': 'charts', 'title': 'Top charts', 'type': 'playlists'},
      ],
      'errors': {'new_albums_malayalam': 'Music provider is currently unavailable'},
    });
    expect(feed.generatedAt, DateTime.utc(2026, 11, 16, 10));
    expect(feed.sections.first.stale, isTrue);
    expect(feed.sections.first.itemCount, 1);
    expect(feed.sections.last.stale, isFalse); // missing -> false
    expect(feed.sections.last.itemCount, 0);
    expect(feed.errors.keys, ['new_albums_malayalam']);
  });

  test('HomeFeed tolerates missing greeting, sections and generated_at', () {
    final feed = HomeFeed.fromJson({});
    expect(feed.greeting, '');
    expect(feed.sections, isEmpty);
    expect(feed.generatedAt, isNull);
  });
}
