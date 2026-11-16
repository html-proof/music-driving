import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/app_theme.dart';
import '../../models/catalog.dart';
import '../../providers/core_providers.dart';
import '../../widgets/common.dart';
import '../../widgets/media_cards.dart';
import '../session/session_controller.dart';

final homeFeedProvider = FutureProvider<HomeFeed>((ref) {
  ref.watch(sessionProvider.select((s) => s.user?.preferences.languages));
  return ref.read(musicRepositoryProvider).home();
});

String localGreeting([DateTime? now]) {
  final h = (now ?? DateTime.now()).hour;
  if (h >= 5 && h < 12) return 'Good morning';
  if (h >= 12 && h < 18) return 'Good afternoon';
  return 'Good evening';
}

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final feed = ref.watch(homeFeedProvider);
    final name = ref.watch(sessionProvider.select((s) => s.user?.displayName));
    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: () => ref.refresh(homeFeedProvider.future),
          child: CustomScrollView(slivers: [
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 16, 8, 0),
                child: Row(children: [
                  Expanded(
                    child: Text('${localGreeting()}${name == null ? '' : ', $name'}',
                        style: const TextStyle(fontSize: 24, fontWeight: FontWeight.bold)),
                  ),
                  IconButton(icon: const Icon(Icons.settings_outlined), onPressed: () => context.go('/profile')),
                ]),
              ),
            ),
            ...feed.when(
              loading: () => [const SliverFillRemaining(child: loadingView)],
              error: (e, _) => [
                SliverFillRemaining(child: ErrorView(error: e, onRetry: () => ref.invalidate(homeFeedProvider))),
              ],
              data: (home) => [
                if (home.fromCache)
                  const SliverToBoxAdapter(
                    child: Padding(
                      padding: EdgeInsets.fromLTRB(16, 8, 16, 0),
                      child: Text('Offline — showing what you saw last time.', style: TextStyle(color: AppColors.textSecondary)),
                    ),
                  ),
                if (home.unavailableLanguages.isNotEmpty && home.sections.isNotEmpty)
                  SliverToBoxAdapter(child: UnavailableLanguagesNotice(languages: home.unavailableLanguages)),
                if (home.sections.isEmpty)
                  SliverFillRemaining(
                    child: ErrorView(
                      error: home.errors.isNotEmpty
                          ? 'The music provider didn\'t return anything right now.'
                          : 'Nothing to show yet.',
                      onRetry: () => ref.invalidate(homeFeedProvider),
                    ),
                  ),
                for (final s in home.sections) SliverToBoxAdapter(child: HomeSectionView(section: s)),
                const SliverToBoxAdapter(child: SizedBox(height: 24)),
              ],
            ),
          ]),
        ),
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
      SectionHeader(section.title, subtitle: section.subtitle),
      list,
    ]);
  }
}
