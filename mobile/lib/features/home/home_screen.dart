import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/errors/app_exception.dart';
import '../../core/theme/app_theme.dart';
import '../../models/catalog.dart';
import '../../providers/core_providers.dart';
import '../../widgets/common.dart';
import '../../widgets/media_cards.dart';
import '../player/player_providers.dart';
import '../session/session_controller.dart';

/// What Home shows: the feed (fresh, or the copy saved on this device), whether a
/// refresh is running, and why the last refresh failed.
class HomeState {
  const HomeState({this.feed, this.fromCache = false, this.refreshing = false, this.error});

  final HomeFeed? feed;

  /// [feed] is the saved copy, not what the server just returned.
  final bool fromCache;
  final bool refreshing;

  /// Why the last refresh failed (the saved feed, if any, is still shown).
  final Object? error;
}

/// Cache-first Home: the saved feed is shown at once while a fresh one loads. A failed
/// or empty refresh keeps whatever is on screen and records why, instead of blanking
/// Home. Never retried automatically: pull to refresh or "Try again" asks again.
class HomeController extends Notifier<HomeState> {
  int _generation = 0;

  @override
  HomeState build() {
    // Compared by value: a new-but-equal languages list must not reload Home.
    ref.watch(sessionProvider.select((s) => s.user?.preferences.languages.join('|')));
    final previous = stateOrNull;
    final generation = ++_generation;
    Future.microtask(() => _load(generation, useCache: previous?.feed == null));
    return HomeState(feed: previous?.feed, fromCache: previous?.fromCache ?? false, refreshing: true);
  }

  Future<void> refresh() => _load(++_generation, useCache: false);

  bool _current(int generation) => generation == _generation && ref.mounted;

  Future<void> _load(int generation, {required bool useCache}) async {
    final repo = ref.read(musicRepositoryProvider);
    if (useCache && state.feed == null) {
      final cached = await repo.cachedHome();
      if (!_current(generation)) return;
      if (cached != null) state = HomeState(feed: cached, fromCache: true, refreshing: true);
    }
    if (!state.refreshing) {
      state = HomeState(feed: state.feed, fromCache: state.fromCache, refreshing: true, error: state.error);
    }
    try {
      final fresh = await repo.home();
      if (!_current(generation)) return;
      final shown = state.feed;
      if (fresh.sections.isEmpty && shown != null && shown.sections.isNotEmpty) {
        // The provider returned nothing (typically while it is blocking us): keep the
        // feed on screen rather than replacing songs with an empty page.
        state = HomeState(
          feed: shown,
          fromCache: true,
          error: const AppException('The music provider didn\'t return anything right now.'),
        );
      } else {
        state = HomeState(feed: fresh);
      }
    } catch (e) {
      if (!_current(generation)) return;
      state = HomeState(feed: state.feed, fromCache: state.feed != null, error: e);
    }
  }
}

final homeFeedProvider = NotifierProvider<HomeController, HomeState>(HomeController.new, retry: (_, _) => null);

String localGreeting([DateTime? now]) {
  final h = (now ?? DateTime.now()).hour;
  if (h >= 5 && h < 12) return 'Good morning';
  if (h >= 12 && h < 18) return 'Good afternoon';
  return 'Good evening';
}

/// Human name for a Home section id (used where only the id is known, e.g. `errors`).
String homeSectionLabel(String id) {
  String cap(String s) => s.isEmpty ? s : '${s[0].toUpperCase()}${s.substring(1)}';
  String suffix(String prefix) => cap(id.substring(prefix.length).replaceAll('_', ' '));
  if (id.startsWith('trending_')) return 'Trending in ${suffix('trending_')}';
  if (id.startsWith('new_albums_')) return 'New albums (${suffix('new_albums_')})';
  if (id.startsWith('new_tracks_')) return 'New songs (${suffix('new_tracks_')})';
  return switch (id) {
    'recently_played' => 'Recently played',
    'made_for_you' => 'Made for you',
    'international_hits' => 'International hits',
    'charts' => 'Top charts',
    'top_artists' => 'Popular artists',
    'popular_albums' => 'Popular albums',
    _ => cap(id.replaceAll('_', ' ')),
  };
}

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final home = ref.watch(homeFeedProvider);
    Future<void> refresh() => ref.read(homeFeedProvider.notifier).refresh();
    final name = ref.watch(sessionProvider.select((s) => s.user?.displayName));
    final feed = home.feed;
    // The app owns the greeting: the device's clock knows the listener's time of day
    // (the server's `greeting` uses its own timezone and already includes the name),
    // and a saved feed must not keep the greeting from when it was saved.
    final greeting = localGreeting();
    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: refresh,
          child: CustomScrollView(physics: const AlwaysScrollableScrollPhysics(), slivers: [
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 16, 8, 0),
                child: Row(children: [
                  Expanded(
                    child: Text('$greeting${name == null ? '' : ', $name'}',
                        style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold)),
                  ),
                  IconButton(icon: const Icon(Icons.settings_outlined), onPressed: () => context.go('/profile')),
                ]),
              ),
            ),
            if (home.refreshing && feed != null)
              const SliverToBoxAdapter(child: LinearProgressIndicator(minHeight: 2)),
            if (feed != null && home.fromCache && home.error != null)
              const SliverToBoxAdapter(child: OfflineHomeBanner()),
            const SliverToBoxAdapter(child: ContinueListeningCard()),
            if (feed == null)
              home.error != null
                  ? SliverFillRemaining(
                      hasScrollBody: false,
                      child: ErrorView(error: home.error!, onRetry: refresh),
                    )
                  : const SliverToBoxAdapter(child: HomeSkeleton())
            else if (feed.sections.every((s) => s.itemCount == 0))
              SliverFillRemaining(
                hasScrollBody: false,
                child: ErrorView(
                  error: feed.errors.isNotEmpty || feed.unavailableLanguages.isNotEmpty
                      ? 'The music provider didn\'t return anything right now.'
                      : 'Nothing to show yet.',
                  onRetry: refresh,
                ),
              )
            else ...[
              if (feed.errors.isNotEmpty || feed.unavailableLanguages.isNotEmpty)
                SliverToBoxAdapter(
                  child: HomeIssuesCard(
                    errors: feed.errors,
                    unavailableLanguages: feed.unavailableLanguages,
                    onRetry: home.refreshing ? null : refresh,
                  ),
                ),
              for (final s in feed.sections)
                if (s.itemCount > 0) SliverToBoxAdapter(child: HomeSectionView(section: s)),
            ],
            const SliverToBoxAdapter(child: SizedBox(height: 24)),
          ]),
        ),
      ),
    );
  }
}

class OfflineHomeBanner extends StatelessWidget {
  const OfflineHomeBanner({super.key});

  @override
  Widget build(BuildContext context) {
    return const Padding(
      padding: EdgeInsets.fromLTRB(16, 8, 16, 0),
      child: Row(children: [
        Icon(Icons.cloud_off, size: 16, color: AppColors.textSecondary),
        SizedBox(width: 8),
        Expanded(
          child: Text('Offline · showing saved Home', style: TextStyle(color: AppColors.textSecondary, fontSize: 13)),
        ),
      ]),
    );
  }
}

/// The song that is playing or was restored from the last session; tap to resume.
class ContinueListeningCard extends ConsumerWidget {
  const ContinueListeningCard({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final track = ref.watch(currentTrackProvider);
    if (track == null) return const SizedBox.shrink();
    final status = ref.watch(playerStatusProvider);
    final active = status == PlayerStatus.playing || status == PlayerStatus.loading || status == PlayerStatus.buffering;
    final handler = ref.read(audioHandlerProvider);
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
      child: Material(
        color: AppColors.surfaceHigh,
        borderRadius: BorderRadius.circular(6),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () => active ? context.push('/player') : handler.play(),
          child: Row(children: [
            ArtworkImage(url: track.artwork.thumb, size: 56, radius: 0),
            const SizedBox(width: 12),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                const Text('Continue listening', style: TextStyle(color: AppColors.textSecondary, fontSize: 12)),
                Text(track.title, maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: const TextStyle(fontWeight: FontWeight.w600)),
                Text(track.artistNames, maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: const TextStyle(color: AppColors.textSecondary, fontSize: 12)),
              ]),
            ),
            Padding(
              padding: const EdgeInsets.only(right: 12),
              child: Icon(active ? Icons.graphic_eq : Icons.play_circle_fill, color: AppColors.accent, size: 32),
            ),
          ]),
        ),
      ),
    );
  }
}

/// Grey placeholder rows while Home loads for the first time with nothing saved.
class HomeSkeleton extends StatelessWidget {
  const HomeSkeleton({super.key});

  @override
  Widget build(BuildContext context) {
    Widget box(double w, double h) => Container(
          width: w,
          height: h,
          decoration: BoxDecoration(color: AppColors.surfaceHigh, borderRadius: BorderRadius.circular(6)),
        );
    return Column(
      key: const ValueKey('home-skeleton'),
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        for (var row = 0; row < 3; row++) ...[
          Padding(padding: const EdgeInsets.fromLTRB(16, 24, 16, 12), child: box(160, 20)),
          SizedBox(
            height: 140,
            child: ListView.separated(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              scrollDirection: Axis.horizontal,
              physics: const NeverScrollableScrollPhysics(),
              itemCount: 4,
              separatorBuilder: (_, _) => const SizedBox(width: 14),
              itemBuilder: (_, _) => box(140, 140),
            ),
          ),
        ],
      ],
    );
  }
}

/// Names the sections and languages that couldn't load, with one retry button.
class HomeIssuesCard extends StatelessWidget {
  const HomeIssuesCard({super.key, required this.errors, required this.unavailableLanguages, this.onRetry});

  final Map<String, String> errors;
  final List<String> unavailableLanguages;
  final VoidCallback? onRetry;

  @override
  Widget build(BuildContext context) {
    final sections = errors.keys.map(homeSectionLabel).toList();
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 16, 0),
      child: Container(
        padding: const EdgeInsets.fromLTRB(12, 8, 4, 8),
        decoration: BoxDecoration(color: AppColors.surface, borderRadius: BorderRadius.circular(6)),
        child: Row(children: [
          const Icon(Icons.info_outline, size: 18, color: AppColors.textSecondary),
          const SizedBox(width: 8),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              if (unavailableLanguages.isNotEmpty)
                Text(UnavailableLanguagesNotice.message(unavailableLanguages),
                    style: const TextStyle(color: AppColors.textSecondary, fontSize: 13)),
              if (sections.isNotEmpty)
                Text('Couldn\'t load: ${sections.join(', ')}',
                    style: const TextStyle(color: AppColors.textSecondary, fontSize: 13)),
            ]),
          ),
          TextButton(onPressed: onRetry, child: const Text('Retry')),
        ]),
      ),
    );
  }
}

/// Shown when some of the user's languages couldn't be loaded, so their songs don't
/// just silently go missing from Home.
class UnavailableLanguagesNotice extends StatelessWidget {
  const UnavailableLanguagesNotice({super.key, required this.languages});
  final List<String> languages;

  static String message(List<String> languages) {
    final names = languages.length == 1
        ? languages.first
        : '${languages.sublist(0, languages.length - 1).join(', ')} and ${languages.last}';
    return '$names songs couldn\'t load right now — the music service is busy. Pull down to try again in a few minutes.';
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Icon(Icons.info_outline, size: 18, color: AppColors.textSecondary),
        const SizedBox(width: 8),
        Expanded(child: Text(message(languages), style: const TextStyle(color: AppColors.textSecondary))),
      ]),
    );
  }
}

class HomeSectionView extends ConsumerWidget {
  const HomeSectionView({super.key, required this.section});
  final HomeSection section;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final handler = ref.read(audioHandlerProvider);
    Widget list;
    switch (section.type) {
      case 'tracks':
        list = HorizontalList(
          itemCount: section.tracks.length,
          itemBuilder: (_, i) {
            final t = section.tracks[i];
            return MediaCard(
              imageUrl: t.artwork.medium,
              title: t.title,
              subtitle: t.artistNames,
              onTap: () => handler.playTracks(section.tracks, startIndex: i, context: 'home:${section.title}'),
            );
          },
        );
      case 'albums':
        list = HorizontalList(
          itemCount: section.albums.length,
          itemBuilder: (_, i) {
            final a = section.albums[i];
            return MediaCard(imageUrl: a.artwork.medium, title: a.title, subtitle: a.artistNames,
                onTap: () => context.push('/album/${a.id}'));
          },
        );
      case 'artists':
        list = HorizontalList(
          height: 190,
          itemCount: section.artists.length,
          itemBuilder: (_, i) {
            final a = section.artists[i];
            return MediaCard(imageUrl: a.artwork.medium, title: a.name, circle: true, size: 130,
                onTap: () => context.push('/artist/${a.id}'));
          },
        );
      case 'playlists':
        list = HorizontalList(
          itemCount: section.playlists.length,
          itemBuilder: (_, i) {
            final p = section.playlists[i];
            return MediaCard(imageUrl: p.artwork.medium, title: p.title, subtitle: p.language,
                onTap: () => context.push('/playlist/${p.id}'));
          },
        );
      default:
        return const SizedBox.shrink();
    }
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      SectionHeader(
        section.title,
        subtitle: section.subtitle,
        action: section.stale
            ? const Padding(
                padding: EdgeInsets.only(right: 8),
                child: Tooltip(
                  message: 'The music service is unavailable; this row is the last copy that loaded.',
                  child: Text('saved copy', style: TextStyle(color: AppColors.textSecondary, fontSize: 12)),
                ),
              )
            : null,
      ),
      list,
    ]);
  }
}
