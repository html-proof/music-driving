import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_theme.dart';
import '../../models/catalog.dart';
import '../../models/track.dart';
import '../../providers/core_providers.dart';
import '../player/player_providers.dart';

/// Lyrics for one catalogue song id. A new id (track change) is a new provider
/// instance, so lyrics always reload for the song that is actually playing.
/// No automatic retry: a failure is almost always the provider being down/blocking us,
/// and Riverpod's default backoff retries would keep hammering it. The panel shows
/// "Try again" instead, and a new song asks again anyway.
final lyricsProvider = FutureProvider.family<Lyrics, String>(
  (ref, songId) => ref.read(musicRepositoryProvider).lyrics(songId),
  retry: (_, _) => null,
);

const lyricsUnavailableMessage = 'Lyrics are currently unavailable.';

/// Loads and shows the lyrics for [track]: live synced lyrics when the source has real
/// LRC timestamps, plain (clearly labelled) lyrics otherwise, or an honest message.
class LyricsPanel extends ConsumerWidget {
  const LyricsPanel({super.key, required this.track, this.padding = const EdgeInsets.symmetric(horizontal: 24)});

  final Track track;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return ref.watch(lyricsProvider(track.id)).when(
          loading: () => const Center(child: CircularProgressIndicator()),
          error: (_, _) => _LyricsMessage(
            icon: Icons.lyrics_outlined,
            message: lyricsUnavailableMessage,
            onRetry: () => ref.invalidate(lyricsProvider(track.id)),
          ),
          data: (lyrics) {
            if (!lyrics.belongsTo(track.id)) {
              return const _LyricsMessage(icon: Icons.lyrics_outlined, message: lyricsUnavailableMessage);
            }
            if (lyrics.instrumental) {
              return const _LyricsMessage(icon: Icons.piano, message: 'This track is instrumental.');
            }
            if (!lyrics.available) {
              return const _LyricsMessage(icon: Icons.lyrics_outlined, message: lyricsUnavailableMessage);
            }
            if (!lyrics.synced || lyrics.lines.isEmpty) {
              final text = lyrics.plainText?.trim() ?? '';
              if (text.isEmpty) return const _LyricsMessage(icon: Icons.lyrics_outlined, message: lyricsUnavailableMessage);
              return _PlainLyrics(text: text, padding: padding);
            }
            // Keyed by song so scroll/highlight state never leaks into the next track.
            return SyncedLyricsView(key: ValueKey('lyrics-${track.id}'), lyrics: lyrics, padding: padding);
          },
        );
  }
}

class _LyricsMessage extends StatelessWidget {
  const _LyricsMessage({required this.icon, required this.message, this.onRetry});
  final IconData icon;
  final String message;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) => Center(
        child: Padding(
          padding: const EdgeInsets.all(32),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            Icon(icon, size: 48, color: AppColors.textSecondary),
            const SizedBox(height: 12),
            Text(message, textAlign: TextAlign.center, style: const TextStyle(fontSize: 16, color: AppColors.textSecondary)),
            if (onRetry != null) ...[
              const SizedBox(height: 12),
              OutlinedButton(onPressed: onRetry, child: const Text('Try again')),
            ],
          ]),
        ),
      );
}

/// Unsynced lyrics are never animated as if they were live.
class _PlainLyrics extends StatelessWidget {
  const _PlainLyrics({required this.text, required this.padding});
  final String text;
  final EdgeInsets padding;

  @override
  Widget build(BuildContext context) => ListView(
        padding: padding.copyWith(top: 16, bottom: 32),
        children: [
          const Row(children: [
            Icon(Icons.info_outline, size: 16, color: AppColors.textSecondary),
            SizedBox(width: 6),
            Expanded(
              child: Text('These lyrics aren\'t time-synced.', style: TextStyle(color: AppColors.textSecondary)),
            ),
          ]),
          const SizedBox(height: 16),
          Text(text, style: const TextStyle(fontSize: 20, height: 1.6, fontWeight: FontWeight.w600)),
        ],
      );
}

/// Live lyrics: the active line is derived from the audio engine's actual position
/// (via [positionProvider]) on every sample, so seeks forward/backward, pauses and
/// buffering stalls are reflected immediately. No independent timer.
class SyncedLyricsView extends ConsumerStatefulWidget {
  const SyncedLyricsView({super.key, required this.lyrics, this.padding = const EdgeInsets.symmetric(horizontal: 24)});
  final Lyrics lyrics;
  final EdgeInsets padding;

  @override
  ConsumerState<SyncedLyricsView> createState() => _SyncedLyricsViewState();
}

class _SyncedLyricsViewState extends ConsumerState<SyncedLyricsView> {
  final _scroll = ScrollController();
  late final List<GlobalKey> _keys = List.generate(widget.lyrics.lines.length, (_) => GlobalKey());
  int _current = -2; // -2 = not yet scrolled; -1 = before the first line
  DateTime _userScrolledAt = DateTime.fromMillisecondsSinceEpoch(0);

  /// After the user scrolls manually, leave them alone for a few seconds.
  bool get _autoScroll => DateTime.now().difference(_userScrolledAt) > const Duration(seconds: 4);

  void _scrollTo(int index, {required bool animate}) {
    if (!_autoScroll || !mounted) return;
    if (index < 0) {
      if (_scroll.hasClients) {
        animate
            ? _scroll.animateTo(0, duration: const Duration(milliseconds: 350), curve: Curves.easeOutCubic)
            : _scroll.jumpTo(0);
      }
      return;
    }
    final ctx = _keys[index].currentContext;
    if (ctx == null) return;
    Scrollable.ensureVisible(
      ctx,
      alignment: 0.4, // keep the active line around the visual centre
      duration: animate ? const Duration(milliseconds: 350) : Duration.zero,
      curve: Curves.easeOutCubic,
    );
  }

  @override
  void dispose() {
    _scroll.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final position = ref.watch(positionProvider).value ?? ref.read(audioHandlerProvider).displayPosition;
    final lines = widget.lyrics.lines;
    final index = widget.lyrics.lineIndexAt(position);
    if (index != _current) {
      // Jumps of more than one line are seeks: snap instead of a long animation.
      final animate = _current >= -1 && (index - _current).abs() <= 1;
      _current = index;
      WidgetsBinding.instance.addPostFrameCallback((_) => _scrollTo(index, animate: animate));
    }
    return NotificationListener<UserScrollNotification>(
      onNotification: (n) {
        if (n.direction != ScrollDirection.idle) _userScrolledAt = DateTime.now();
        return false;
      },
      // Every line is laid out (lyrics are short) so any line can be scrolled to
      // immediately after a long seek.
      child: SingleChildScrollView(
        controller: _scroll,
        padding: widget.padding.copyWith(top: 24, bottom: 280),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (var i = 0; i < lines.length; i++)
              _LyricLineTile(
                key: _keys[i],
                text: lines[i].text,
                state: i == index ? LineState.active : (i < index ? LineState.past : LineState.upcoming),
                onTap: () {
                  _userScrolledAt = DateTime.fromMillisecondsSinceEpoch(0);
                  ref.read(audioHandlerProvider).seek(lines[i].time);
                },
              ),
          ],
        ),
      ),
    );
  }
}

enum LineState { past, active, upcoming }

class _LyricLineTile extends StatelessWidget {
  const _LyricLineTile({super.key, required this.text, required this.state, required this.onTap});
  final String text;
  final LineState state;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final color = switch (state) {
      LineState.active => Colors.white,
      LineState.past => Colors.white54,
      LineState.upcoming => Colors.white30,
    };
    return Semantics(
      selected: state == LineState.active,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(6),
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 8),
          child: AnimatedScale(
            scale: state == LineState.active ? 1.0 : 0.96,
            alignment: Alignment.centerLeft,
            duration: const Duration(milliseconds: 250),
            child: AnimatedDefaultTextStyle(
              duration: const Duration(milliseconds: 250),
              style: TextStyle(fontSize: 26, height: 1.3, fontWeight: FontWeight.w800, color: color),
              child: Text(text.isEmpty ? '♪' : text),
            ),
          ),
        ),
      ),
    );
  }
}
