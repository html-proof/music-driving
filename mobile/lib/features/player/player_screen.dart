import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/config/app_config.dart';
import '../../core/theme/app_theme.dart';
import '../../models/track.dart';
import '../../providers/core_providers.dart';
import '../../widgets/common.dart';
import '../../widgets/track_tile.dart';
import '../library/library_providers.dart';
import '../lyrics/lyrics_view.dart';
import 'player_providers.dart';
import 'widgets/player_controls.dart';
import 'widgets/seek_bar.dart';

/// Full-screen player with two modes:
///  * normal — large artwork, title/artist/like, progress, controls, queue/lyrics/quality;
///  * lyrics — full-height live lyrics with the progress bar and controls kept at the bottom.
/// Both modes drive the single shared audio handler.
class PlayerScreen extends ConsumerStatefulWidget {
  const PlayerScreen({super.key, this.startInLyrics = false});
  final bool startInLyrics;

  @override
  ConsumerState<PlayerScreen> createState() => _PlayerScreenState();
}

class _PlayerScreenState extends ConsumerState<PlayerScreen> {
  late bool _lyrics = widget.startInLyrics;

  @override
  Widget build(BuildContext context) {
    final track = ref.watch(currentTrackProvider);
    if (track == null) {
      return Scaffold(appBar: AppBar(), body: const EmptyView(icon: Icons.music_off, message: 'Nothing is playing'));
    }
    final handler = ref.read(audioHandlerProvider);
    final status = ref.watch(playerStatusProvider);
    final tint = _tintFor(track);

    return Scaffold(
      backgroundColor: AppColors.background,
      body: AnimatedContainer(
        duration: const Duration(milliseconds: 600),
        decoration: BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topCenter,
            end: Alignment.bottomCenter,
            colors: [tint, Color.lerp(tint, AppColors.background, 0.75)!, AppColors.background],
            stops: const [0, 0.55, 1],
          ),
        ),
        child: SafeArea(
          child: Column(children: [
            _TopBar(
              title: _lyrics ? 'Lyrics' : _contextLabel(handler.playContext),
              onMore: () => showTrackMenu(context, ref, track),
            ),
            Expanded(
              child: AnimatedSwitcher(
                duration: const Duration(milliseconds: 250),
                child: _lyrics
                    ? Column(key: const ValueKey('lyrics-mode'), children: [
                        _CompactHeader(track: track),
                        Expanded(child: LyricsPanel(track: track)),
                      ])
                    : _ArtworkMode(key: const ValueKey('artwork-mode'), track: track),
              ),
            ),
            if (status == PlayerStatus.error) _ErrorBanner(message: handler.errorMessage, onRetry: handler.play),
            const SizedBox(height: 4),
            const SeekBar(),
            PlayerControls(compact: _lyrics),
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 4, 12, 8),
              child: Row(children: [
                TextButton.icon(
                  onPressed: () => _showQualitySheet(context, ref),
                  icon: const Icon(Icons.graphic_eq, size: 18),
                  label: Text(_qualityLabel(handler.activeStreamQuality ?? handler.quality)),
                ),
                const Spacer(),
                IconButton(
                  tooltip: _lyrics ? 'Hide lyrics' : 'Lyrics',
                  isSelected: _lyrics,
                  selectedIcon: const Icon(Icons.lyrics, color: AppColors.accent),
                  icon: const Icon(Icons.lyrics_outlined),
                  onPressed: () => setState(() => _lyrics = !_lyrics),
                ),
                IconButton(tooltip: 'Queue', icon: const Icon(Icons.queue_music), onPressed: () => context.push('/queue')),
              ]),
            ),
          ]),
        ),
      ),
    );
  }

  /// A stable, muted colour per album/song (no image decoding needed).
  static Color _tintFor(Track t) {
    final seed = (t.album?.id ?? t.id).hashCode;
    return HSLColor.fromAHSL(1, (seed % 360).toDouble(), 0.35, 0.30).toColor();
  }

  static String _contextLabel(String? c) {
    if (c == null) return 'Your music';
    final i = c.indexOf(':');
    return i < 0 ? c : c.substring(i + 1);
  }

  static String _qualityLabel(String q) => AppConfig.audioQualities[q]?.split(' ').first ?? q;

  void _showQualitySheet(BuildContext context, WidgetRef ref) {
    final handler = ref.read(audioHandlerProvider);
    showModalBottomSheet(
      context: context,
      backgroundColor: AppColors.surface,
      showDragHandle: true,
      builder: (ctx) => SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          const Text('Audio quality', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
          if (handler.activeStreamQuality != null && handler.activeStreamQuality != handler.quality)
            Padding(
              padding: const EdgeInsets.all(12),
              child: Text(
                'This song isn\'t available in ${AppConfig.audioQualities[handler.quality]}; '
                'playing ${AppConfig.audioQualities[handler.activeStreamQuality]}.',
                style: const TextStyle(color: AppColors.textSecondary),
              ),
            ),
          RadioGroup<String>(
            groupValue: handler.quality,
            onChanged: (q) async {
              if (q == null) return;
              Navigator.pop(ctx);
              // Applied immediately (current song reloads at the same position) and
              // saved on the device by the handler.
              await handler.setQuality(q);
            },
            child: Column(children: [
              for (final e in AppConfig.audioQualities.entries) RadioListTile<String>(value: e.key, title: Text(e.value)),
            ]),
          ),
        ]),
      ),
    );
  }
}

class _TopBar extends StatelessWidget {
  const _TopBar({required this.title, required this.onMore});
  final String title;
  final VoidCallback onMore;

  @override
  Widget build(BuildContext context) => SizedBox(
        height: 56,
        child: Row(children: [
          IconButton(
            tooltip: 'Close player',
            icon: const Icon(Icons.keyboard_arrow_down, size: 30),
            onPressed: () => context.pop(),
          ),
          Expanded(
            child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
              const Text('PLAYING FROM', style: TextStyle(fontSize: 10, letterSpacing: 1, color: AppColors.textSecondary)),
              Text(title, maxLines: 1, overflow: TextOverflow.ellipsis,
                  style: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold)),
            ]),
          ),
          IconButton(tooltip: 'More', icon: const Icon(Icons.more_vert), onPressed: onMore),
        ]),
      );
}

class _ArtworkMode extends StatelessWidget {
  const _ArtworkMode({super.key, required this.track});
  final Track track;

  @override
  Widget build(BuildContext context) => LayoutBuilder(builder: (context, c) {
        final art = (c.maxWidth - 48).clamp(120.0, c.maxHeight - 90);
        return Column(children: [
          const Spacer(),
          Hero(
            tag: 'artwork',
            child: DecoratedBox(
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(8),
                boxShadow: const [BoxShadow(color: Colors.black54, blurRadius: 24, offset: Offset(0, 10))],
              ),
              child: ArtworkImage(url: track.artwork.best, size: art, radius: 8),
            ),
          ),
          const Spacer(),
          _TitleRow(track: track),
        ]);
      });
}

class _TitleRow extends ConsumerWidget {
  const _TitleRow({required this.track, this.small = false});
  final Track track;
  final bool small;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final liked = ref.watch(isLikedProvider(track.id));
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 24),
      child: Row(children: [
        Expanded(
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text(track.title, maxLines: 1, overflow: TextOverflow.ellipsis,
                style: TextStyle(fontSize: small ? 16 : 22, fontWeight: FontWeight.bold)),
            GestureDetector(
              onTap: () {
                final a = track.artists.where((a) => a.id != null).firstOrNull;
                if (a != null) context.push('/artist/${a.id}');
              },
              child: Text(track.artistNames, maxLines: 1, overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: small ? 13 : 15, color: AppColors.textSecondary)),
            ),
          ]),
        ),
        IconButton(
          tooltip: liked ? 'Remove from Liked Songs' : 'Like',
          icon: Icon(liked ? Icons.favorite : Icons.favorite_border,
              color: liked ? AppColors.accent : Colors.white, size: small ? 24 : 28),
          onPressed: () async {
            try {
              await ref.read(likedSongsProvider.notifier).toggle(track);
            } catch (e) {
              if (context.mounted) showError(context, e);
            }
          },
        ),
      ]),
    );
  }
}

class _CompactHeader extends StatelessWidget {
  const _CompactHeader({required this.track});
  final Track track;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.only(left: 24, top: 4, bottom: 4),
        child: Row(children: [
          ArtworkImage(url: track.artwork.thumb ?? track.artwork.best, size: 48, radius: 4),
          Expanded(child: _TitleRow(track: track, small: true)),
        ]),
      );
}

class _ErrorBanner extends StatelessWidget {
  const _ErrorBanner({required this.message, required this.onRetry});
  final String? message;
  final Future<void> Function() onRetry;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 4),
        child: Row(children: [
          const Icon(Icons.error_outline, color: Colors.redAccent, size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: Text(message ?? 'This song can\'t be played right now.',
                maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontSize: 13)),
          ),
          TextButton(onPressed: onRetry, child: const Text('Retry')),
        ]),
      );
}
