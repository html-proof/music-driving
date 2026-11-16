import 'package:audio_service/audio_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../../core/theme/app_theme.dart';
import '../../../providers/core_providers.dart';
import '../../../widgets/common.dart';
import '../player_providers.dart';

/// Persistent mini player. Uses the same handler as the full player (no second engine).
class MiniPlayer extends ConsumerWidget {
  const MiniPlayer({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final track = ref.watch(currentTrackProvider);
    if (track == null) return const SizedBox.shrink();
    final state = ref.watch(playbackStateProvider).value;
    final playing = state?.playing ?? false;
    final loading = state?.processingState == AudioProcessingState.loading ||
        state?.processingState == AudioProcessingState.buffering;
    final position = ref.watch(positionProvider).value ?? Duration.zero;
    final duration = ref.watch(currentMediaItemProvider).value?.duration ?? track.durationValue;
    final handler = ref.read(audioHandlerProvider);

    return GestureDetector(
      onTap: () => context.push('/player'),
      onVerticalDragEnd: (d) {
        if ((d.primaryVelocity ?? 0) < -200) context.push('/player');
      },
      child: Container(
        margin: const EdgeInsets.fromLTRB(8, 0, 8, 4),
        decoration: BoxDecoration(color: AppColors.surfaceHigh, borderRadius: BorderRadius.circular(8)),
        clipBehavior: Clip.antiAlias,
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Padding(
            padding: const EdgeInsets.all(6),
            child: Row(children: [
              Hero(tag: 'artwork', child: ArtworkImage(url: track.artwork.thumb, size: 44)),
              const SizedBox(width: 10),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Text(track.title, maxLines: 1, overflow: TextOverflow.ellipsis,
                      style: const TextStyle(fontWeight: FontWeight.w600)),
                  Text(track.artistNames, maxLines: 1, overflow: TextOverflow.ellipsis,
                      style: const TextStyle(color: AppColors.textSecondary, fontSize: 12)),
                ]),
              ),
              if (loading)
                const Padding(
                  padding: EdgeInsets.all(12),
                  child: SizedBox(width: 24, height: 24, child: CircularProgressIndicator(strokeWidth: 2)),
                )
              else
                IconButton(
                  tooltip: playing ? 'Pause' : 'Play',
                  icon: Icon(playing ? Icons.pause : Icons.play_arrow, size: 30),
                  onPressed: playing ? handler.pause : handler.play,
                ),
              IconButton(tooltip: 'Next', icon: const Icon(Icons.skip_next), onPressed: handler.skipToNext),
            ]),
          ),
          LinearProgressIndicator(
            minHeight: 2,
            value: duration.inMilliseconds > 0 ? (position.inMilliseconds / duration.inMilliseconds).clamp(0.0, 1.0) : 0,
            backgroundColor: Colors.white12,
            color: Colors.white,
          ),
        ]),
      ),
    );
  }
}
