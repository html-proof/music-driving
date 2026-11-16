import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../core/theme/app_theme.dart';
import '../features/library/library_providers.dart';
import '../features/player/player_providers.dart';
import '../features/playlists/add_to_playlist_sheet.dart';
import '../models/track.dart';
import '../providers/core_providers.dart';
import 'common.dart';

/// A song row. [onTap] normally starts playback of the surrounding list at this song.
class TrackTile extends ConsumerWidget {
  const TrackTile({
    super.key,
    required this.track,
    required this.onTap,
    this.index,
    this.showArtwork = true,
    this.trailing,
    this.typeLabel,
    this.showDuration = false,
  });

  final Track track;
  final VoidCallback onTap;
  final int? index;
  final bool showArtwork;
  final Widget? trailing;

  /// Shown before the artists, e.g. "Song" in mixed search results.
  final String? typeLabel;

  /// Append the length when it is known (0 means unknown and shows nothing, not 0:00).
  final bool showDuration;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final isCurrent = ref.watch(currentTrackProvider.select((t) => t?.id == track.id));
    final enabled = track.playable;
    final details = [
      ?typeLabel,
      if (track.artistNames.isNotEmpty) track.artistNames,
      if (showDuration && track.hasDuration) formatDuration(track.durationValue),
      if (!enabled) 'unavailable',
    ].join(' · ');
    return ListTile(
      enabled: enabled,
      contentPadding: const EdgeInsets.only(left: 16, right: 4),
      leading: showArtwork
          ? ArtworkImage(url: track.artwork.thumb, size: 48)
          : SizedBox(
              width: 28,
              child: Text('${(index ?? 0) + 1}', textAlign: TextAlign.center, style: const TextStyle(color: AppColors.textSecondary)),
            ),
      title: Text(
        track.title,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        style: TextStyle(color: isCurrent ? AppColors.accent : null, fontWeight: FontWeight.w500),
      ),
      subtitle: Row(children: [
        if (track.isExplicit)
          Container(
            margin: const EdgeInsets.only(right: 6),
            padding: const EdgeInsets.symmetric(horizontal: 4),
            decoration: BoxDecoration(color: AppColors.textSecondary, borderRadius: BorderRadius.circular(2)),
            child: const Text('E', style: TextStyle(fontSize: 10, color: Colors.black, fontWeight: FontWeight.bold)),
          ),
        Expanded(
          child: Text(
            details,
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            style: const TextStyle(color: AppColors.textSecondary),
          ),
        ),
      ]),
      onTap: enabled ? onTap : null,
      trailing: trailing ??
          IconButton(
            icon: const Icon(Icons.more_vert),
            tooltip: 'More options',
            onPressed: () => showTrackMenu(context, ref, track),
          ),
    );
  }
}

Future<void> showTrackMenu(BuildContext context, WidgetRef ref, Track track) {
  return showModalBottomSheet(
    context: context,
    backgroundColor: AppColors.surface,
    showDragHandle: true,
    builder: (sheetContext) => Consumer(builder: (context, ref, _) {
      final liked = ref.watch(isLikedProvider(track.id));
      final handler = ref.read(audioHandlerProvider);
      final artist = track.artists.where((a) => a.id != null).firstOrNull;
      void close() => Navigator.of(sheetContext).pop();
      return SafeArea(
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          ListTile(
            leading: ArtworkImage(url: track.artwork.thumb),
            title: Text(track.title, maxLines: 1, overflow: TextOverflow.ellipsis),
            subtitle: Text(track.artistNames, maxLines: 1, overflow: TextOverflow.ellipsis),
          ),
          const Divider(height: 1),
          ListTile(
            leading: Icon(liked ? Icons.favorite : Icons.favorite_border, color: liked ? AppColors.accent : null),
            title: Text(liked ? 'Remove from Liked Songs' : 'Add to Liked Songs'),
            onTap: () async {
              close();
              try {
                await ref.read(likedSongsProvider.notifier).toggle(track);
              } catch (e) {
                if (context.mounted) showError(context, e);
              }
            },
          ),
          ListTile(
            leading: const Icon(Icons.playlist_add),
            title: const Text('Add to playlist'),
            onTap: () {
              close();
              showAddToPlaylistSheet(context, [track]);
            },
          ),
          ListTile(
            leading: const Icon(Icons.queue_play_next),
            title: const Text('Play next'),
            onTap: () {
              close();
              handler.playNextInQueue(track);
              showMessage(context, 'Will play next');
            },
          ),
          ListTile(
            leading: const Icon(Icons.queue_music),
            title: const Text('Add to queue'),
            onTap: () {
              close();
              handler.addToQueue(track);
              showMessage(context, 'Added to queue');
            },
          ),
          if (track.album?.id != null)
            ListTile(
              leading: const Icon(Icons.album),
              title: const Text('Go to album'),
              onTap: () {
                close();
                context.push('/album/${track.album!.id}');
              },
            ),
          if (artist != null)
            ListTile(
              leading: const Icon(Icons.person),
              title: Text('Go to ${artist.name}'),
              onTap: () {
                close();
                context.push('/artist/${artist.id}');
              },
            ),
        ]),
      );
    }),
  );
}
