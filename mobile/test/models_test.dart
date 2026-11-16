import 'package:flutter_test/flutter_test.dart';
import 'package:melodia/models/catalog.dart';
import 'package:melodia/models/track.dart';

void main() {
  test('Track parses the backend schema', () {
    final t = Track.fromJson({
      'id': 'tyler-herro',
      'track_id': '32408795',
      'title': 'Tyler Herro',
      'artists': [
        {'name': 'Jack Harlow', 'id': 'jack-harlow', 'numeric_id': '817522'},
      ],
      'album': {'id': 'tyler-herro', 'numeric_id': '3487503', 'title': 'Tyler Herro'},
      'duration': 156,
      'genres': ['Hip Hop'],
      'is_explicit': true,
      'artwork': {'small': 's.jpg', 'medium': 'm.jpg', 'large': 'l.jpg'},
      'playable': true,
    });
    expect(t.artistNames, 'Jack Harlow');
    expect(t.durationValue, const Duration(seconds: 156));
    expect(t.artwork.best, 'l.jpg');
    expect(Track.fromJson(t.toJson()).album!.numericId, '3487503');
  });

  test('StreamInfo staleness uses expires_at minus 2 minutes', () {
    final soon = StreamInfo.fromJson({
      'url': 'u',
      'quality': 'high',
      'bitrate_kbps': 128,
      'expires_at': DateTime.now().toUtc().add(const Duration(minutes: 1)).toIso8601String(),
    });
    final later = StreamInfo.fromJson({
      'url': 'u',
      'quality': 'high',
      'bitrate_kbps': 128,
      'expires_at': DateTime.now().toUtc().add(const Duration(hours: 1)).toIso8601String(),
    });
    expect(soon.isStale, isTrue);
    expect(later.isStale, isFalse);
  });

  test('Lyrics.lineIndexAt finds the active line', () {
    final l = Lyrics.fromJson({
      'available': true,
      'synced': true,
      'lines': [
        {'time_ms': 1000, 'text': 'a'},
        {'time_ms': 5000, 'text': 'b'},
        {'time_ms': 9000, 'text': 'c'},
      ],
    });
    expect(l.lineIndexAt(Duration.zero), -1);
    expect(l.lineIndexAt(const Duration(milliseconds: 1000)), 0);
    expect(l.lineIndexAt(const Duration(seconds: 7)), 1);
    expect(l.lineIndexAt(const Duration(minutes: 5)), 2);
  });
}
