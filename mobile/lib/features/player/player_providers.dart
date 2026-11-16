import 'package:audio_service/audio_service.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/track.dart';
import '../../providers/core_providers.dart';

final playbackStateProvider = StreamProvider<PlaybackState>((ref) {
  final h = ref.watch(audioHandlerProvider);
  return h.playbackState;
});

final currentMediaItemProvider = StreamProvider<MediaItem?>((ref) => ref.watch(audioHandlerProvider).mediaItem);

/// The playing track (decoded from the MediaItem extras).
final currentTrackProvider = Provider<Track?>((ref) {
  final item = ref.watch(currentMediaItemProvider).value;
  final json = item?.extras?['track'];
  return json is Map ? Track.fromJson(Map<String, dynamic>.from(json)) : null;
});

final queueProvider = StreamProvider<List<MediaItem>>((ref) => ref.watch(audioHandlerProvider).queue);

/// Single position source for every player UI (full player, mini player, lyrics).
/// It samples the audio engine's real position (just_audio `AudioPlayer.position`,
/// which is derived from the native player clock) — it never extrapolates time on its
/// own, so seeks, buffering stalls and pauses are reflected on the next sample (≤100 ms).
/// Uses the handler's display position so a restored-but-not-yet-loaded song shows
/// where it will resume.
final positionProvider = StreamProvider<Duration>((ref) {
  final h = ref.watch(audioHandlerProvider);
  return Stream.periodic(const Duration(milliseconds: 100), (_) => h.displayPosition).distinct();
});

final bufferedPositionProvider =
    StreamProvider<Duration>((ref) => ref.watch(audioHandlerProvider).bufferedPositionStream);

/// The seven user-facing playback states, derived from the one handler's state.
enum PlayerStatus { idle, loading, buffering, playing, paused, completed, error }

PlayerStatus playerStatusOf(PlaybackState? s) {
  if (s == null) return PlayerStatus.idle;
  return switch (s.processingState) {
    AudioProcessingState.idle => PlayerStatus.idle,
    AudioProcessingState.loading => PlayerStatus.loading,
    AudioProcessingState.buffering => PlayerStatus.buffering,
    AudioProcessingState.completed => PlayerStatus.completed,
    AudioProcessingState.error => PlayerStatus.error,
    AudioProcessingState.ready => s.playing ? PlayerStatus.playing : PlayerStatus.paused,
  };
}

final playerStatusProvider = Provider<PlayerStatus>((ref) => playerStatusOf(ref.watch(playbackStateProvider).value));
