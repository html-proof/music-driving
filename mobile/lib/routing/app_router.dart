import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/discovery/detail_screens.dart';
import '../features/home/home_screen.dart';
import '../features/library/library_screen.dart';
import '../features/player/player_screen.dart';
import '../features/player/queue_screen.dart';
import '../features/player/widgets/mini_player.dart';
import '../features/profile/profile_screen.dart';
import '../features/search/search_screen.dart';
import '../features/session/session_controller.dart';
import '../widgets/common.dart';

final rootNavigatorKey = GlobalKey<NavigatorState>();

final routerProvider = Provider<GoRouter>((ref) {
  // No login screens: wait for the device session, show a retry screen if the very
  // first start can't reach the server (later starts fall back to cached data).
  final status = ValueNotifier<SessionStatus>(ref.read(sessionProvider).status);
  ref.listen(sessionProvider, (_, next) => status.value = next.status);
  ref.onDispose(status.dispose);

  return GoRouter(
    navigatorKey: rootNavigatorKey,
    initialLocation: '/home',
    refreshListenable: status,
    redirect: (context, state) {
      final path = state.matchedLocation;
      return switch (status.value) {
        SessionStatus.starting => path == '/splash' ? null : '/splash',
        SessionStatus.failed => path == '/unavailable' ? null : '/unavailable',
        SessionStatus.ready => (path == '/splash' || path == '/unavailable') ? '/home' : null,
      };
    },
    routes: [
      GoRoute(path: '/splash', builder: (_, _) => const Scaffold(body: loadingView)),
      GoRoute(path: '/unavailable', builder: (_, _) => const StartupErrorScreen()),
      StatefulShellRoute.indexedStack(
        builder: (context, state, shell) => AppShell(shell: shell),
        branches: [
          StatefulShellBranch(routes: [GoRoute(path: '/home', builder: (_, _) => const HomeScreen())]),
          StatefulShellBranch(routes: [GoRoute(path: '/search', builder: (_, _) => const SearchScreen())]),
          StatefulShellBranch(routes: [GoRoute(path: '/library', builder: (_, _) => const LibraryScreen())]),
          StatefulShellBranch(routes: [GoRoute(path: '/profile', builder: (_, _) => const ProfileScreen())]),
        ],
      ),
      // Detail pages keep the mini player visible.
      GoRoute(path: '/album/:id', builder: (_, s) => WithMiniPlayer(child: AlbumScreen(id: s.pathParameters['id']!))),
      GoRoute(path: '/artist/:id', builder: (_, s) => WithMiniPlayer(child: ArtistScreen(id: s.pathParameters['id']!))),
      GoRoute(
        path: '/playlist/:id',
        builder: (_, s) => WithMiniPlayer(child: ProviderPlaylistScreen(id: s.pathParameters['id']!)),
      ),
      GoRoute(
        path: '/my-playlist/:id',
        builder: (_, s) => WithMiniPlayer(child: UserPlaylistScreen(id: s.pathParameters['id']!)),
      ),
      GoRoute(path: '/liked', builder: (_, _) => const WithMiniPlayer(child: LikedSongsScreen())),
      GoRoute(path: '/player', pageBuilder: (_, s) => _slideUp(s, const PlayerScreen())),
      GoRoute(path: '/queue', builder: (_, _) => const QueueScreen()),
      GoRoute(path: '/lyrics', pageBuilder: (_, s) => _slideUp(s, const PlayerScreen(startInLyrics: true))),
    ],
  );
});

Page<void> _slideUp(GoRouterState state, Widget child) => CustomTransitionPage(
      key: state.pageKey,
      child: child,
      transitionsBuilder: (_, animation, _, child) => SlideTransition(
        position: Tween(begin: const Offset(0, 1), end: Offset.zero)
            .animate(CurvedAnimation(parent: animation, curve: Curves.easeOutCubic)),
        child: child,
      ),
    );

class WithMiniPlayer extends StatelessWidget {
  const WithMiniPlayer({super.key, required this.child});
  final Widget child;

  @override
  Widget build(BuildContext context) => Column(children: [
        Expanded(child: child),
        const Material(color: Colors.black, child: SafeArea(top: false, child: MiniPlayer())),
      ]);
}

class AppShell extends StatelessWidget {
  const AppShell({super.key, required this.shell});
  final StatefulNavigationShell shell;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: shell,
      bottomNavigationBar: Column(mainAxisSize: MainAxisSize.min, children: [
        const MiniPlayer(),
        NavigationBar(
          height: 64,
          selectedIndex: shell.currentIndex,
          onDestinationSelected: (i) => shell.goBranch(i, initialLocation: i == shell.currentIndex),
          destinations: const [
            NavigationDestination(icon: Icon(Icons.home_outlined), selectedIcon: Icon(Icons.home), label: 'Home'),
            NavigationDestination(icon: Icon(Icons.search), selectedIcon: Icon(Icons.saved_search), label: 'Search'),
            NavigationDestination(
                icon: Icon(Icons.library_music_outlined), selectedIcon: Icon(Icons.library_music), label: 'Your Library'),
            NavigationDestination(icon: Icon(Icons.person_outline), selectedIcon: Icon(Icons.person), label: 'Profile'),
          ],
        ),
      ]),
    );
  }
}

class StartupErrorScreen extends ConsumerWidget {
  const StartupErrorScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final error = ref.watch(sessionProvider.select((s) => s.error)) ?? 'Can\'t reach the server.';
    return Scaffold(
      body: SafeArea(
        child: ErrorView(error: error, onRetry: () => ref.read(sessionProvider.notifier).start()),
      ),
    );
  }
}
