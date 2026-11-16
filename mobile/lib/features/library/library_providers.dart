import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/errors/app_exception.dart';
import '../../models/catalog.dart';
import '../../models/track.dart';
import '../../models/user.dart';
import '../../providers/core_providers.dart';
import '../session/session_controller.dart';

/// Liked songs, with optimistic like/unlike that rolls back if the server refuses.
class LikedSongsController extends AsyncNotifier<List<Track>> {
  @override
  Future<List<Track>> build() async {
    final userId = ref.watch(sessionProvider.select((s) => s.user?.id));
    if (userId == null) return const [];
    return ref.read(libraryRepositoryProvider).likedSongs();
  }

  bool isLiked(String songId) => state.value?.any((t) => t.id == songId) ?? false;

  Future<void> toggle(Track track) async {
    final current = state.value ?? const <Track>[];
    final liked = current.any((t) => t.id == track.id);
    state = AsyncData(liked ? current.where((t) => t.id != track.id).toList() : [track, ...current]);
    try {
      final repo = ref.read(libraryRepositoryProvider);
      liked ? await repo.unlike(track.id) : await repo.like(track.id);
    } on AppException {
      state = AsyncData(current);
      rethrow;
    }
  }
}

final likedSongsProvider = AsyncNotifierProvider<LikedSongsController, List<Track>>(LikedSongsController.new);

final isLikedProvider = Provider.family<bool, String>((ref, songId) {
  final liked = ref.watch(likedSongsProvider).value ?? const [];
  return liked.any((t) => t.id == songId);
});

final userPlaylistsProvider = FutureProvider<List<UserPlaylist>>((ref) async {
  final userId = ref.watch(sessionProvider.select((s) => s.user?.id));
  if (userId == null) return const [];
  return ref.read(libraryRepositoryProvider).playlists();
});

final userPlaylistProvider = FutureProvider.family<UserPlaylist, String>(
    (ref, id) => ref.read(libraryRepositoryProvider).playlist(id));

final followedArtistsProvider = FutureProvider<List<ArtistSummary>>((ref) async {
  final userId = ref.watch(sessionProvider.select((s) => s.user?.id));
  if (userId == null) return const [];
  return ref.read(libraryRepositoryProvider).followedArtists();
});

final recentlyPlayedProvider = FutureProvider<List<Track>>((ref) async {
  final userId = ref.watch(sessionProvider.select((s) => s.user?.id));
  if (userId == null) return const [];
  return ref.read(libraryRepositoryProvider).recentlyPlayed();
});

final recommendationsProvider =
    FutureProvider<Recommendations>((ref) => ref.read(libraryRepositoryProvider).recommendations());
