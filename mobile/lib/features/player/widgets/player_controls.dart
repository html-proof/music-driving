import 'package:audio_service/audio_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_theme.dart';
import '../../../providers/core_providers.dart';
import '../player_providers.dart';

/// Shuffle · Previous · Play/Pause · Next · Repeat. Every button calls the one shared
/// audio handler — the same methods the notification, lock screen and Bluetooth
/// buttons reach through audio_service — so behaviour is identical everywhere.
class PlayerControls extends ConsumerWidget {
  const PlayerControls({super.key, this.compact = false});

  /// Smaller variant for lyrics mode.
  final bool compact;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final handler = ref.read(audioHandlerProvider);
    final state = ref.watch(playbackStateProvider).value;
    final status = playerStatusOf(state);
    final playing = state?.playing ?? false;
    final busy = status == PlayerStatus.loading || status == PlayerStatus.buffering;
    final shuffle = state?.shuffleMode == AudioServiceShuffleMode.all;
    final repeat = state?.repeatMode ?? AudioServiceRepeatMode.none;
    final big = compact ? 56.0 : 68.0;
    final skip = compact ? 34.0 : 40.0;

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 12),
      child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        IconButton(
          tooltip: shuffle ? 'Shuffle on' : 'Shuffle off',
          icon: Icon(Icons.shuffle, color: shuffle ? AppColors.accent : Colors.white),
          onPressed: () => handler.setShuffleMode(shuffle ? AudioServiceShuffleMode.none : AudioServiceShuffleMode.all),
        ),
        IconButton(tooltip: 'Previous', iconSize: skip, icon: const Icon(Icons.skip_previous_rounded), onPressed: handler.skipToPrevious),
        SizedBox(
          width: big,
          height: big,
          child: FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: Colors.white,
              disabledBackgroundColor: Colors.white70,
              shape: const CircleBorder(),
              padding: EdgeInsets.zero,
              minimumSize: Size(big, big),
            ),
            // While buffering the button still works (pausing a stalled stream is valid).
            onPressed: status == PlayerStatus.loading ? null : (playing ? handler.pause : handler.play),
            child: Semantics(
              label: playing ? 'Pause' : 'Play',
              child: Tooltip(
                message: playing ? 'Pause' : 'Play',
                child: busy && !playing
                    ? const SizedBox(width: 26, height: 26, child: CircularProgressIndicator(strokeWidth: 2.5, color: Colors.black))
                    : Icon(playing ? Icons.pause_rounded : Icons.play_arrow_rounded, size: big * 0.56, color: Colors.black),
              ),
            ),
          ),
        ),
        IconButton(tooltip: 'Next', iconSize: skip, icon: const Icon(Icons.skip_next_rounded), onPressed: handler.skipToNext),
        IconButton(
          tooltip: switch (repeat) {
            AudioServiceRepeatMode.none => 'Repeat off',
            AudioServiceRepeatMode.one => 'Repeat one',
            _ => 'Repeat all',
          },
          icon: Icon(
            repeat == AudioServiceRepeatMode.one ? Icons.repeat_one : Icons.repeat,
            color: repeat == AudioServiceRepeatMode.none ? Colors.white : AppColors.accent,
          ),
          // Off → All → One → Off (Spotify order).
          onPressed: () => handler.setRepeatMode(switch (repeat) {
            AudioServiceRepeatMode.none => AudioServiceRepeatMode.all,
            AudioServiceRepeatMode.all || AudioServiceRepeatMode.group => AudioServiceRepeatMode.one,
            AudioServiceRepeatMode.one => AudioServiceRepeatMode.none,
          }),
        ),
      ]),
    );
  }
}
