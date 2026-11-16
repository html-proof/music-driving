import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/app_theme.dart';
import '../../providers/core_providers.dart';
import '../../widgets/common.dart';
import '../../widgets/track_tile.dart';
import '../discovery/detail_screens.dart';
import '../playlists/add_to_playlist_sheet.dart';
import 'library_providers.dart';

class LibraryScreen extends ConsumerStatefulWidget {
  const LibraryScreen({super.key});
  @override
  ConsumerState<LibraryScreen> createState() => _LibraryScreenState();
}

class _LibraryScreenState extends ConsumerState<LibraryScreen> {
  String _filter = 'playlists';

  Future<void> _createPlaylist() async {
    final name = await promptPlaylistName(context);
    if (name == null || name.isEmpty) return;
    try {
      final p = await ref.read(libraryRepositoryProvider).createPlaylist(name);
      ref.invalidate(userPlaylistsProvider);
      if (mounted) context.push('/my-playlist/${p.id}');
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final liked = ref.watch(likedSongsProvider);
    return Scaffold(
      appBar: AppBar(
        title: const Text('Your Library', style: TextStyle(fontWeight: FontWeight.bold)),
        actions: [IconButton(tooltip: 'Create playlist', icon: const Icon(Icons.add), onPressed: _createPlaylist)],
      ),
      body: RefreshIndicator(
        onRefresh: () async {
          ref.invalidate(likedSongsProvider);
          ref.invalidate(userPlaylistsProvider);
          ref.invalidate(followedArtistsProvider);
          ref.invalidate(recentlyPlayedProvider);
        },
        child: ListView(children: [
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            padding: const EdgeInsets.symmetric(horizontal: 16),
            child: Row(children: [
              for (final f in const {'playlists': 'Playlists', 'artists': 'Artists', 'recent': 'Recently played'}.entries)
                Padding(
                  padding: const EdgeInsets.only(right: 8),
                  child: ChoiceChip(
                    label: Text(f.value),
                    selected: _filter == f.key,
                    onSelected: (_) => setState(() => _filter = f.key),
                  ),
                ),
            ]),
          ),
          const SizedBox(height: 8),
          ListTile(
            leading: Container(
              width: 56,
              height: 56,
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(4),
                gradient: const LinearGradient(colors: [Color(0xFF4A39EA), Color(0xFF8AA5E6)]),
              ),
              child: const Icon(Icons.favorite, color: Colors.white),
            ),
            title: const Text('Liked Songs'),
            subtitle: Text('Playlist · ${liked.value?.length ?? 0} songs'),
            onTap: () => context.push('/liked'),
          ),
          ..._section(),
          const SizedBox(height: 24),
        ]),
      ),
    );
  }

  List<Widget> _section() {
    switch (_filter) {
      case 'artists':
        return ref.watch(followedArtistsProvider).when(
              loading: () => [const Padding(padding: EdgeInsets.all(24), child: loadingView)],
              error: (e, _) => [ErrorView(error: e, onRetry: () => ref.invalidate(followedArtistsProvider))],
              data: (artists) => artists.isEmpty
                  ? [const EmptyView(icon: Icons.person_outline, message: 'Artists you follow appear here')]
                  : [
                      for (final a in artists)
                        ListTile(
                          leading: ArtworkImage(url: a.artwork.thumb, size: 56, circle: true, icon: Icons.person),
                          title: Text(a.name),
                          subtitle: const Text('Artist'),
                          onTap: () => context.push('/artist/${a.id}'),
                        ),
                    ],
            );
      case 'recent':
        final handler = ref.read(audioHandlerProvider);
        return ref.watch(recentlyPlayedProvider).when(
              loading: () => [const Padding(padding: EdgeInsets.all(24), child: loadingView)],
              error: (e, _) => [ErrorView(error: e, onRetry: () => ref.invalidate(recentlyPlayedProvider))],
              data: (tracks) => tracks.isEmpty
                  ? [const EmptyView(icon: Icons.history, message: 'Songs you play appear here')]
                  : [
                      for (var i = 0; i < tracks.length; i++)
                        TrackTile(
                          track: tracks[i],
                          onTap: () => handler.playTracks(tracks, startIndex: i, context: 'library:Recently played'),
                        ),
                    ],
            );
      default:
        return ref.watch(userPlaylistsProvider).when(
              loading: () => [const Padding(padding: EdgeInsets.all(24), child: loadingView)],
              error: (e, _) => [ErrorView(error: e, onRetry: () => ref.invalidate(userPlaylistsProvider))],
              data: (lists) => [
                for (final p in lists)
                  ListTile(
                    leading: ArtworkImage(url: p.artwork.firstOrNull, size: 56, icon: Icons.queue_music),
                    title: Text(p.name),
                    subtitle: Text('Playlist · ${p.trackCount} songs'),
                    onTap: () => context.push('/my-playlist/${p.id}'),
                  ),
                if (lists.isEmpty)
                  Padding(
                    padding: const EdgeInsets.all(24),
                    child: OutlinedButton.icon(
                      onPressed: _createPlaylist,
                      icon: const Icon(Icons.add),
                      label: const Text('Create your first playlist'),
                    ),
                  ),
              ],
            );
    }
  }
}

class LikedSongsScreen extends ConsumerWidget {
  const LikedSongsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      body: ref.watch(likedSongsProvider).when(
            loading: () => loadingView,
            error: (e, _) =>
                Scaffold(appBar: AppBar(), body: ErrorView(error: e, onRetry: () => ref.invalidate(likedSongsProvider))),
            data: (tracks) => CollectionView(
              title: 'Liked Songs',
              subtitle: '${tracks.length} songs',
              imageUrl: tracks.firstOrNull?.artwork.best,
              tracks: tracks,
              context_: 'library:Liked Songs',
            ),
          ),
    );
  }
}

class UserPlaylistScreen extends ConsumerWidget {
  const UserPlaylistScreen({super.key, required this.id});
  final String id;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final repo = ref.read(libraryRepositoryProvider);
    void refresh() {
      ref.invalidate(userPlaylistProvider(id));
      ref.invalidate(userPlaylistsProvider);
    }

    return Scaffold(
      body: ref.watch(userPlaylistProvider(id)).when(
            loading: () => loadingView,
            error: (e, _) => Scaffold(appBar: AppBar(), body: ErrorView(error: e, onRetry: refresh)),
            data: (p) => CollectionView(
              title: p.name,
              subtitle: [if (p.description?.isNotEmpty ?? false) p.description!, '${p.tracks.length} songs'].join(' · '),
              imageUrl: p.artwork.firstOrNull ?? p.tracks.firstOrNull?.artwork.best,
              tracks: p.tracks,
              context_: 'playlist:${p.name}',
              extraActions: [
                IconButton(
                  tooltip: 'Rename',
                  icon: const Icon(Icons.edit_outlined),
                  onPressed: () async {
                    final name = await promptPlaylistName(context, initial: p.name, title: 'Rename playlist');
                    if (name == null || name.isEmpty || name == p.name) return;
                    try {
                      await repo.updatePlaylist(p.id, name: name);
                      refresh();
                    } catch (e) {
                      if (context.mounted) showError(context, e);
                    }
                  },
                ),
                IconButton(
                  tooltip: 'Delete playlist',
                  icon: const Icon(Icons.delete_outline),
                  onPressed: () async {
                    final ok = await showDialog<bool>(
                      context: context,
                      builder: (ctx) => AlertDialog(
                        title: const Text('Delete playlist?'),
                        content: Text('"${p.name}" will be permanently deleted.'),
                        actions: [
                          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
                          TextButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Delete')),
                        ],
                      ),
                    );
                    if (ok != true) return;
                    try {
                      await repo.deletePlaylist(p.id);
                      ref.invalidate(userPlaylistsProvider);
                      if (context.mounted) context.pop();
                    } catch (e) {
                      if (context.mounted) showError(context, e);
                    }
                  },
                ),
              ],
              trackTrailing: (track) => IconButton(
                tooltip: 'Remove from playlist',
                icon: const Icon(Icons.remove_circle_outline, color: AppColors.textSecondary),
                onPressed: () async {
                  try {
                    await repo.removeFromPlaylist(p.id, track.id);
                    refresh();
                  } catch (e) {
                    if (context.mounted) showError(context, e);
                  }
                },
              ),
            ),
          ),
    );
  }
}
