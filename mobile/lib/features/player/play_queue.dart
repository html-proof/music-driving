import 'dart:math';

import '../../core/config/app_config.dart';
import '../../models/track.dart';

enum RepeatMode { off, all, one }

enum PreviousAction { restartCurrent, playPrevious }

/// Spotify-style previous: >3 s into the song (or nothing before it) restarts it.
PreviousAction decidePrevious({required Duration position, required bool hasPrevious}) {
  if (position > AppConfig.restartThreshold || !hasPrevious) return PreviousAction.restartCurrent;
  return PreviousAction.playPrevious;
}

/// Pure queue model: items in original order plus a play order (identity or shuffled).
/// Kept free of audio code so it can be unit-tested.
class PlayQueue {
  PlayQueue({List<Track>? items, List<int>? order, this.position = 0, this.shuffle = false, this.repeat = RepeatMode.off, Random? random})
      : items = List.of(items ?? const []),
        order = List.of(order ?? List.generate(items?.length ?? 0, (i) => i)),
        _random = random ?? Random();

  final List<Track> items;
  List<int> order;
  int position; // index into [order]
  bool shuffle;
  RepeatMode repeat;
  final Random _random;

  bool get isEmpty => items.isEmpty;
  int get length => items.length;
  Track? get current => isEmpty ? null : items[order[position]];

  /// Tracks in the order they will play.
  List<Track> get playOrder => [for (final i in order) items[i]];

  bool get hasNext => position < order.length - 1 || (repeat == RepeatMode.all && order.isNotEmpty);
  bool get hasPrevious => position > 0 || (repeat == RepeatMode.all && order.length > 1);

  void replace(List<Track> tracks, {int startIndex = 0}) {
    items
      ..clear()
      ..addAll(tracks);
    order = List.generate(tracks.length, (i) => i);
    position = tracks.isEmpty ? 0 : startIndex.clamp(0, tracks.length - 1);
    if (shuffle) _shuffleKeepingCurrent();
  }

  /// Advance for an explicit "next" press. Returns false at the end of a non-repeating queue.
  bool next() {
    if (isEmpty) return false;
    if (position < order.length - 1) {
      position++;
      return true;
    }
    if (repeat == RepeatMode.all) {
      if (shuffle) _reshuffleForNewCycle();
      position = 0;
      return true;
    }
    return false;
  }

  bool previous() {
    if (isEmpty) return false;
    if (position > 0) {
      position--;
      return true;
    }
    if (repeat == RepeatMode.all && order.length > 1) {
      position = order.length - 1;
      return true;
    }
    return false;
  }

  /// Jump to an index in [playOrder].
  void jumpTo(int playIndex) {
    if (playIndex >= 0 && playIndex < order.length) position = playIndex;
  }

  void setShuffle(bool enabled) {
    if (enabled == shuffle) return;
    shuffle = enabled;
    if (isEmpty) return;
    if (enabled) {
      _shuffleKeepingCurrent();
    } else {
      final currentItem = order[position];
      order = List.generate(items.length, (i) => i);
      position = currentItem;
    }
  }

  void _shuffleKeepingCurrent() {
    if (isEmpty) return;
    final currentItem = order[position];
    final rest = List.generate(items.length, (i) => i)..remove(currentItem);
    rest.shuffle(_random);
    order = [currentItem, ...rest];
    position = 0;
  }

  void _reshuffleForNewCycle() {
    order.shuffle(_random);
  }

  /// Insert right after the current song.
  void playNext(Track track) {
    items.add(track);
    order.insert(isEmpty ? 0 : position + 1, items.length - 1);
  }

  void addToEnd(Track track) {
    items.add(track);
    order.add(items.length - 1);
  }

  /// Remove the entry at [playIndex] of [playOrder]. Returns whether the current track was removed.
  bool removeAt(int playIndex) {
    if (playIndex < 0 || playIndex >= order.length) return false;
    final itemIndex = order.removeAt(playIndex);
    items.removeAt(itemIndex);
    order = [for (final i in order) i > itemIndex ? i - 1 : i];
    final removedCurrent = playIndex == position;
    if (playIndex < position) position--;
    if (position >= order.length) position = max(0, order.length - 1);
    return removedCurrent;
  }

  /// Reorder within [playOrder] (drag & drop in the queue screen).
  void move(int from, int to) {
    if (from == to || from < 0 || to < 0 || from >= order.length || to >= order.length) return;
    final currentItem = order[position];
    final v = order.removeAt(from);
    order.insert(to, v);
    position = order.indexOf(currentItem);
  }

  Map<String, dynamic> toJson() => {
        'items': items.map((t) => t.toJson()).toList(),
        'order': order,
        'position': position,
        'shuffle': shuffle,
        'repeat': repeat.name,
      };

  factory PlayQueue.fromJson(Map<String, dynamic> j) {
    final items = tracksFrom(j['items']);
    final order = (j['order'] as List? ?? []).cast<int>();
    final valid = order.length == items.length && order.toSet().length == items.length;
    return PlayQueue(
      items: items,
      order: valid ? order : null,
      position: ((j['position'] as int?) ?? 0).clamp(0, items.isEmpty ? 0 : items.length - 1),
      shuffle: j['shuffle'] as bool? ?? false,
      repeat: RepeatMode.values.firstWhere((m) => m.name == j['repeat'], orElse: () => RepeatMode.off),
    );
  }
}
