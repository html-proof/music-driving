import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/app_theme.dart';
import '../../models/catalog.dart';
import '../../models/track.dart';
import '../../providers/core_providers.dart';
import '../../widgets/common.dart';
import '../../widgets/media_cards.dart';
import '../../widgets/track_tile.dart';
import '../library/library_providers.dart';
import '../playlists/add_to_playlist_sheet.dart';

// No automatic retries: a failure is almost always the provider being down or blocking
// us, and Riverpod's default backoff would keep hammering it. The screens offer "Try again".
final albumProvider = FutureProvider.family<AlbumDetail, String>(
  (ref, id) => ref.read(musicRepositoryProvider).album(id),
  retry: (_, _) => null,
);
final artistProvider = FutureProvider.family<ArtistDetail, String>(
  (ref, id) => ref.read(musicRepositoryProvider).artist(id),
  retry: (_, _) => null,
);
final providerPlaylistProvider = FutureProvider.family<PlaylistDetail, String>(
  (ref, id) => ref.read(musicRepositoryProvider).playlist(id),
  retry: (_, _) => null,
);

/// Shared header + track list layout for albums and playlists.
class CollectionView extends ConsumerWidget {
  const CollectionView({
    super.key,
    required this.title,
    required this.subtitle,
    required this.imageUrl,
    required this.tracks,
    required this.context_,
    this.numbered = false,
    this.extraActions = const [],
    this.trackTrailing,
    this.footer,
  });

  final String title;
  final String subtitle;
  final String? imageUrl;
  final List<Track> tracks;
  final String context_;
  final bool numbered;
  final List<Widget> extraActions;
  final Widget Function(Track)? trackTrailing;
  final Widget? footer;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final handler = ref.read(audioHandlerProvider);
    final playable = tracks.where((t) => t.playable).toList();
    return CustomScrollView(slivers: [
      SliverAppBar(pinned: true, title: Text(title, maxLines: 1, overflow: TextOverflow.ellipsis)),
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Center(child: ArtworkImage(url: imageUrl, size: 200, radius: 6, icon: Icons.album)),
            const SizedBox(height: 16),
            Text(title, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
            const SizedBox(height: 4),
            Text(subtitle, style: const TextStyle(color: AppColors.textSecondary)),
            const SizedBox(height: 8),
            Row(children: [
              ...extraActions,
              if (tracks.isNotEmpty)
                IconButton(
                  tooltip: 'Add all to playlist',
                  icon: const Icon(Icons.playlist_add),
                  onPressed: () => showAddToPlaylistSheet(context, playable),
                ),
              const Spacer(),
              IconButton(
                tooltip: 'Shuffle play',
                icon: const Icon(Icons.shuffle),
                onPressed: playable.isEmpty ? null : () => handler.playTracks(playable, context: context_, shuffle: true),
              ),
              IconButton.filled(
                tooltip: 'Play',
                iconSize: 32,
                style: IconButton.styleFrom(backgroundColor: AppColors.accent, foregroundColor: Colors.black),
                icon: const Icon(Icons.play_arrow),
                onPressed: playable.isEmpty ? null : () => handler.playTracks(playable, context: context_, shuffle: false),
              ),
            ]),
          ]),
        ),
      ),
      if (tracks.isEmpty)
        const SliverToBoxAdapter(child: EmptyView(icon: Icons.music_off, message: 'No songs here yet')),
      SliverList.builder(
        itemCount: tracks.length,
        itemBuilder: (_, i) => TrackTile(
          track: tracks[i],
          index: i,
          showArtwork: !numbered,
          trailing: trackTrailing?.call(tracks[i]),
          onTap: () => handler.playTracks(tracks, startIndex: i, context: context_),
        ),
      ),
      if (footer != null) SliverToBoxAdapter(child: footer),
      const SliverToBoxAdapter(child: SizedBox(height: 24)),
    ]);
  }
}

class AlbumScreen extends ConsumerWidget {
  const AlbumScreen({super.key, required this.id});
  final String id;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      body: ref.watch(albumProvider(id)).when(
            loading: () => loadingView,
            error: (e, _) => Scaffold(appBar: AppBar(), body: ErrorView(error: e, onRetry: () => ref.invalidate(albumProvider(id)))),
            data: (a) => CollectionView(
              title: a.title,
              subtitle: [
                a.artistNames,
                if (a.releaseDate != null) a.releaseDate!.split('-').first,
                '${a.tracks.length} songs',
              ].join(' · '),
              imageUrl: a.artwork.best,
              tracks: a.tracks,
              numbered: true,
              context_: 'album:${a.title}',
              footer: a.label == null
                  ? null
                  : Padding(
                      padding: const EdgeInsets.all(16),
                      child: Text('© ${a.label}', style: const TextStyle(color: AppColors.textSecondary, fontSize: 12)),
                    ),
            ),
          ),
    );
  }
}

class ProviderPlaylistScreen extends ConsumerWidget {
  const ProviderPlaylistScreen({super.key, required this.id});
  final String id;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Scaffold(
      body: ref.watch(providerPlaylistProvider(id)).when(
            loading: () => loadingView,
            error: (e, _) =>
                Scaffold(appBar: AppBar(), body: ErrorView(error: e, onRetry: () => ref.invalidate(providerPlaylistProvider(id)))),
            data: (p) => CollectionView(
              title: p.title,
              subtitle: [if (p.language != null) p.language!, '${p.tracks.length} songs', if (p.playCount != null) '${p.playCount} plays']
                  .join(' · '),
              imageUrl: p.artwork.best,
              tracks: p.tracks,
              context_: 'playlist:${p.title}',
            ),
          ),
    );
  }
}

class ArtistScreen extends ConsumerStatefulWidget {
  const ArtistScreen({super.key, required this.id});
  final String id;
  @override
  ConsumerState<ArtistScreen> createState() => _ArtistScreenState();
}

class _ArtistScreenState extends ConsumerState<ArtistScreen> {
  bool? _followed; // optimistic override
  final _more = <Track>[];
  int _page = 1;
  bool _hasMore = true;
  bool _loadingMore = false;

  Future<void> _loadMore(String numericId) async {
    if (_loadingMore) return;
    setState(() => _loadingMore = true);
    try {
      final r = await ref.read(musicRepositoryProvider).artistTracks(numericId, ++_page);
      setState(() {
        _more.addAll(r.items);
        _hasMore = r.hasMore;
      });
    } catch (e) {
      _page--;
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => _loadingMore = false);
    }
  }

  Future<void> _toggleFollow(ArtistDetail a) async {
    final now = !(_followed ?? a.isFollowed);
    setState(() => _followed = now);
    try {
      final repo = ref.read(libraryRepositoryProvider);
      now ? await repo.follow(a.id) : await repo.unfollow(a.id);
      ref.invalidate(followedArtistsProvider);
    } catch (e) {
      setState(() => _followed = !now);
      if (mounted) showError(context, e);
    }
  }

  @override
  Widget build(BuildContext context) {
    final handler = ref.read(audioHandlerProvider);
    return Scaffold(
      body: ref.watch(artistProvider(widget.id)).when(
            loading: () => loadingView,
            error: (e, _) =>
                Scaffold(appBar: AppBar(), body: ErrorView(error: e, onRetry: () => ref.invalidate(artistProvider(widget.id)))),
            data: (a) {
              final followed = _followed ?? a.isFollowed;
              final tracks = [...a.topTracks, ..._more.where((t) => !a.topTracks.contains(t))];
              return CustomScrollView(slivers: [
                SliverAppBar(pinned: true, title: Text(a.name)),
                SliverToBoxAdapter(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(children: [
                      ArtworkImage(url: a.artwork.best, size: 180, circle: true, icon: Icons.person),
                      const SizedBox(height: 12),
                      Text(a.name, style: const TextStyle(fontSize: 26, fontWeight: FontWeight.bold)),
                      if (a.followerCount != null)
                        Text('${a.followerCount} fans', style: const TextStyle(color: AppColors.textSecondary)),
                      const SizedBox(height: 12),
                      Row(children: [
                        OutlinedButton(onPressed: () => _toggleFollow(a), child: Text(followed ? 'Following' : 'Follow')),
                        const Spacer(),
                        IconButton.filled(
                          iconSize: 32,
                          style: IconButton.styleFrom(backgroundColor: AppColors.accent, foregroundColor: Colors.black),
                          icon: const Icon(Icons.play_arrow),
                          onPressed: tracks.isEmpty ? null : () => handler.playTracks(tracks, context: 'artist:${a.name}'),
                        ),
                      ]),
                    ]),
                  ),
                ),
                const SliverToBoxAdapter(child: SectionHeader('Popular')),
                SliverList.builder(
                  itemCount: tracks.length,
                  itemBuilder: (_, i) => TrackTile(
                    track: tracks[i],
                    onTap: () => handler.playTracks(tracks, startIndex: i, context: 'artist:${a.name}'),
                  ),
                ),
                if (a.numericId != null && _hasMore)
                  SliverToBoxAdapter(
                    child: Padding(
                      padding: const EdgeInsets.all(8),
                      child: Center(
                        child: _loadingMore
                            ? const CircularProgressIndicator()
                            : TextButton(onPressed: () => _loadMore(a.numericId!), child: const Text('Show more songs')),
                      ),
                    ),
                  ),
                if (a.similarArtists.isNotEmpty) ...[
                  const SliverToBoxAdapter(child: SectionHeader('Fans also like')),
                  SliverToBoxAdapter(
                    child: HorizontalList(
                      height: 190,
                      itemCount: a.similarArtists.length,
                      itemBuilder: (_, i) {
                        final s = a.similarArtists[i];
                        return MediaCard(imageUrl: s.artwork.medium, title: s.name, circle: true, size: 130,
                            onTap: () => context.push('/artist/${s.id}'));
                      },
                    ),
                  ),
                ],
                const SliverToBoxAdapter(child: SizedBox(height: 24)),
              ]);
            },
          ),
    );
  }
}
