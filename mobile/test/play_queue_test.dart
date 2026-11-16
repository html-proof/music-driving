import 'dart:math';

import 'package:flutter_test/flutter_test.dart';
import 'package:melodia/features/player/play_queue.dart';
import 'package:melodia/models/track.dart';

List<Track> tracks(int n) => List.generate(n, (i) => Track(id: 't$i', title: 'Track $i'));

void main() {
  group('decidePrevious', () {
    test('more than 3 seconds in restarts the song', () {
      expect(decidePrevious(position: const Duration(milliseconds: 3001), hasPrevious: true), PreviousAction.restartCurrent);
    });
    test('3 seconds or less goes to the previous song', () {
      expect(decidePrevious(position: const Duration(seconds: 3), hasPrevious: true), PreviousAction.playPrevious);
      expect(decidePrevious(position: Duration.zero, hasPrevious: true), PreviousAction.playPrevious);
    });
    test('no previous song restarts the current one', () {
      expect(decidePrevious(position: const Duration(seconds: 1), hasPrevious: false), PreviousAction.restartCurrent);
    });
  });

  group('PlayQueue', () {
    test('next/previous without repeat stop at the edges', () {
      final q = PlayQueue()..replace(tracks(3));
      expect(q.current!.id, 't0');
      expect(q.hasPrevious, isFalse);
      expect(q.next(), isTrue);
      expect(q.next(), isTrue);
      expect(q.current!.id, 't2');
      expect(q.next(), isFalse);
      expect(q.current!.id, 't2');
      expect(q.previous(), isTrue);
      expect(q.current!.id, 't1');
    });

    test('repeat all wraps around both ways', () {
      final q = PlayQueue(repeat: RepeatMode.all)..replace(tracks(3), startIndex: 2);
      expect(q.next(), isTrue);
      expect(q.current!.id, 't0');
      expect(q.previous(), isTrue);
      expect(q.current!.id, 't2');
    });

    test('shuffle keeps the current song playing and covers every song once', () {
      final q = PlayQueue(random: Random(1))..replace(tracks(10), startIndex: 4);
      q.setShuffle(true);
      expect(q.current!.id, 't4');
      expect(q.position, 0);
      expect(q.playOrder.map((t) => t.id).toSet().length, 10);
      q.next();
      q.setShuffle(false);
      // Back to original order, positioned on whatever song was playing.
      expect(q.playOrder.map((t) => t.id).toList(), [for (var i = 0; i < 10; i++) 't$i']);
      expect(q.current, isNotNull);
    });

    test('playNext inserts after current, addToEnd appends', () {
      final q = PlayQueue()..replace(tracks(3));
      q.playNext(const Track(id: 'x', title: 'X'));
      q.addToEnd(const Track(id: 'y', title: 'Y'));
      expect(q.playOrder.map((t) => t.id).toList(), ['t0', 'x', 't1', 't2', 'y']);
    });

    test('removeAt before current keeps the same song current', () {
      final q = PlayQueue()..replace(tracks(4), startIndex: 2);
      expect(q.removeAt(0), isFalse);
      expect(q.current!.id, 't2');
      expect(q.playOrder.map((t) => t.id).toList(), ['t1', 't2', 't3']);
      expect(q.removeAt(1), isTrue); // removing the current song
      expect(q.current!.id, 't3');
    });

    test('move keeps the current song tracked', () {
      final q = PlayQueue()..replace(tracks(4), startIndex: 1);
      q.move(1, 3);
      expect(q.playOrder.map((t) => t.id).toList(), ['t0', 't2', 't3', 't1']);
      expect(q.current!.id, 't1');
    });

    test('json round trip', () {
      final q = PlayQueue(random: Random(2), repeat: RepeatMode.one)..replace(tracks(5), startIndex: 3);
      q.setShuffle(true);
      final r = PlayQueue.fromJson(q.toJson());
      expect(r.playOrder.map((t) => t.id), q.playOrder.map((t) => t.id));
      expect(r.current!.id, q.current!.id);
      expect(r.repeat, RepeatMode.one);
      expect(r.shuffle, isTrue);
    });
  });
}
