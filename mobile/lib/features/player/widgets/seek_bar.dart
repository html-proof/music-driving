import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/theme/app_theme.dart';
import '../../../providers/core_providers.dart';
import '../../../widgets/common.dart';
import '../player_providers.dart';

/// Draggable/tappable progress bar. While dragging it shows the drag position and only
/// seeks on release, so playback doesn't stutter; tapping seeks immediately.
class SeekBar extends ConsumerStatefulWidget {
  const SeekBar({super.key});

  @override
  ConsumerState<SeekBar> createState() => _SeekBarState();
}

class _SeekBarState extends ConsumerState<SeekBar> {
  double? _dragValue;
  bool _showRemaining = false;

  @override
  Widget build(BuildContext context) {
    final position = ref.watch(positionProvider).value ?? Duration.zero;
    final buffered = ref.watch(bufferedPositionProvider).value ?? Duration.zero;
    final item = ref.watch(currentMediaItemProvider).value;
    final state = ref.watch(playbackStateProvider).value;
    final duration = item?.duration ?? Duration.zero;
    final maxMs = duration.inMilliseconds.toDouble();
    final enabled = maxMs > 0;
    final value = (_dragValue ?? position.inMilliseconds.toDouble()).clamp(0.0, enabled ? maxMs : 0.0);
    final shown = Duration(milliseconds: value.round());
    final buffering = state?.processingState.name == 'buffering' || state?.processingState.name == 'loading';

    return Column(
      children: [
        Stack(
          alignment: Alignment.center,
          children: [
            // Buffered range behind the slider.
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 24),
              child: LinearProgressIndicator(
                value: enabled ? (buffered.inMilliseconds / maxMs).clamp(0.0, 1.0) : 0,
                minHeight: 3,
                backgroundColor: Colors.transparent,
                color: Colors.white24,
              ),
            ),
            Slider(
              min: 0,
              max: enabled ? maxMs : 1,
              value: enabled ? value : 0,
              onChangeStart: enabled ? (v) => setState(() => _dragValue = v) : null,
              onChanged: enabled ? (v) => setState(() => _dragValue = v) : null,
              onChangeEnd: enabled
                  ? (v) async {
                      await ref.read(audioHandlerProvider).seek(Duration(milliseconds: v.round()));
                      if (mounted) setState(() => _dragValue = null);
                    }
                  : null,
            ),
          ],
        ),
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 24),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(formatDuration(shown), style: const TextStyle(color: AppColors.textSecondary, fontSize: 12)),
              if (buffering)
                const SizedBox(width: 12, height: 12, child: CircularProgressIndicator(strokeWidth: 1.5)),
              GestureDetector(
                onTap: () => setState(() => _showRemaining = !_showRemaining),
                child: Text(
                  !enabled
                      ? '--:--'
                      : _showRemaining
                          ? '-${formatDuration(duration - shown)}'
                          : formatDuration(duration),
                  style: const TextStyle(color: AppColors.textSecondary, fontSize: 12),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
