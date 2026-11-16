import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/theme/app_theme.dart';
import '../../models/track.dart';
import '../../providers/core_providers.dart';
import '../../widgets/common.dart';
import '../library/library_providers.dart';

Future<String?> promptPlaylistName(BuildContext context, {String initial = '', String title = 'New playlist'}) {
  final controller = TextEditingController(text: initial);
  return showDialog<String>(
    context: context,
    builder: (ctx) => AlertDialog(
      title: Text(title),
      content: TextField(
        controller: controller,
        autofocus: true,
        maxLength: 200,
        decoration: const InputDecoration(hintText: 'Playlist name'),
        onSubmitted: (v) => Navigator.pop(ctx, v.trim()),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
        TextButton(onPressed: () => Navigator.pop(ctx, controller.text.trim()), child: const Text('Save')),
      ],
    ),
  );
}

Future<void> showAddToPlaylistSheet(BuildContext context, List<Track> tracks) {
  return showModalBottomSheet(
    context: context,
    backgroundColor: AppColors.surface,
    showDragHandle: true,
    isScrollControlled: true,
    builder: (sheetContext) => Consumer(builder: (context, ref, _) {
      final playlists = ref.watch(userPlaylistsProvider);

      Future<void> addTo(String playlistId, String name) async {
        Navigator.of(sheetContext).pop();
        try {
          final r = await ref.read(libraryRepositoryProvider).addToPlaylist(playlistId, tracks.map((t) => t.id).toList());
          ref.invalidate(userPlaylistsProvider);
          ref.invalidate(userPlaylistProvider(playlistId));
          if (!context.mounted) return;
          if (r.added.isNotEmpty) {
            showMessage(context, 'Added to $name');
          } else if (r.already.isNotEmpty) {
            showMessage(context, 'Already in $name');
          } else {
            showMessage(context, 'Couldn\'t add: ${r.failed.values.join(', ')}');
          }
        } catch (e) {
          if (context.mounted) showError(context, e);
        }
      }

      return SafeArea(
        child: ConstrainedBox(
          constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(context).height * 0.7),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            const Text('Add to playlist', style: TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
            ListTile(
              leading: const Icon(Icons.add),
              title: const Text('New playlist'),
              onTap: () async {
                final name = await promptPlaylistName(context);
                if (name == null || name.isEmpty) return;
                try {
                  final p = await ref.read(libraryRepositoryProvider).createPlaylist(name);
                  await addTo(p.id, p.name);
                } catch (e) {
                  if (context.mounted) showError(context, e);
                }
              },
            ),
            Flexible(
              child: playlists.when(
                loading: () => const Padding(padding: EdgeInsets.all(24), child: loadingView),
                error: (e, _) => ErrorView(error: e, onRetry: () => ref.invalidate(userPlaylistsProvider)),
                data: (list) => ListView(
                  shrinkWrap: true,
                  children: [
                    for (final p in list)
                      ListTile(
                        leading: ArtworkImage(url: p.artwork.firstOrNull, icon: Icons.queue_music),
                        title: Text(p.name),
                        subtitle: Text('${p.trackCount} songs'),
                        onTap: () => addTo(p.id, p.name),
                      ),
                  ],
                ),
              ),
            ),
          ]),
        ),
      );
    }),
  );
}
