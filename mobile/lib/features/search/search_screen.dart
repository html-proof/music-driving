import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/config/app_config.dart';
import '../../core/errors/app_exception.dart';
import '../../core/theme/app_theme.dart';
import '../../models/catalog.dart';
import '../../providers/core_providers.dart';
import '../../widgets/common.dart';
import '../../widgets/track_tile.dart';

final searchHistoryProvider = FutureProvider<List<Map<String, dynamic>>>((ref) async {
  try {
    return await ref.read(musicRepositoryProvider).searchHistory();
  } on AppException {
    return const [];
  }
});

class SearchScreen extends ConsumerStatefulWidget {
  const SearchScreen({super.key});
  @override
  ConsumerState<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends ConsumerState<SearchScreen> {
  final _controller = TextEditingController();
  Timer? _debounce;
  CancelToken? _cancel;
  String _query = '';
  bool _loading = false;
  Object? _error;
  SearchResults? _results;
  int _requestId = 0;

  void _onChanged(String value) {
    _debounce?.cancel();
    // Cancel immediately, including the debounce window, so an older response
    // cannot replace results for text the user has already changed.
    _cancel?.cancel();
    ++_requestId;
    if (value.trim().isEmpty) {
      _search('');
      return;
    }
    _debounce = Timer(AppConfig.searchDebounce, () => _search(value));
  }

  Future<void> _search(String raw, {bool save = false}) async {
    final q = raw.trim();
    final requestId = ++_requestId;
    _cancel?.cancel(); // drop the previous in-flight request
    if (q.isEmpty) {
      setState(() {
        _query = '';
        _results = null;
        _error = null;
        _loading = false;
      });
      return;
    }
    final token = _cancel = CancelToken();
    setState(() {
      _query = q;
      _loading = true;
      _error = null;
    });
    try {
      final r = await ref.read(musicRepositoryProvider).search(q, cancelToken: token, save: save);
      if (!mounted || token.isCancelled || requestId != _requestId) return;
      setState(() {
        _results = r;
        _loading = false;
      });
      if (save) ref.invalidate(searchHistoryProvider);
    } catch (e) {
      if (!mounted || token.isCancelled || requestId != _requestId) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _cancel?.cancel();
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Column(children: [
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
            child: TextField(
              controller: _controller,
              textInputAction: TextInputAction.search,
              decoration: InputDecoration(
                hintText: 'What do you want to listen to?',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: _controller.text.isEmpty
                    ? null
                    : IconButton(
                        icon: const Icon(Icons.close),
                        onPressed: () {
                          _controller.clear();
                          _search('');
                        },
                      ),
              ),
              onChanged: (v) {
                setState(() {});
                _onChanged(v);
              },
              onSubmitted: (v) => _search(v, save: true),
            ),
          ),
          Expanded(child: _body()),
        ]),
      ),
    );
  }

  Widget _body() {
    if (_query.isEmpty) return _history();
    if (_loading && _results == null) return loadingView;
    if (_error != null) return ErrorView(error: _error!, onRetry: () => _search(_query));
    final r = _results;
    if (r == null) return const SizedBox.shrink();
    if (r.isEmpty) {
      return r.errors.isNotEmpty
          ? ErrorView(error: r.errors.values.first, onRetry: () => _search(_query))
          : EmptyView(icon: Icons.search_off, message: 'No results for "$_query"');
    }
    final handler = ref.read(audioHandlerProvider);
    return ListView(children: [
      if (_loading) const LinearProgressIndicator(minHeight: 2),
      if (r.errors.isNotEmpty)
        Padding(
          padding: const EdgeInsets.all(16),
          child: Text('Some results couldn\'t load: ${r.errors.keys.join(', ')}',
              style: const TextStyle(color: AppColors.textSecondary)),
        ),
      if (r.artists.isNotEmpty) ...[
        const SectionHeader('Artists'),
        for (final a in r.artists.take(4))
          ListTile(
            leading: ArtworkImage(url: a.artwork.thumb, circle: true, icon: Icons.person),
            title: Text(a.name),
            subtitle: const Text('Artist'),
            onTap: () => context.push('/artist/${a.id}'),
          ),
      ],
      if (r.songs.isNotEmpty) ...[
        const SectionHeader('Songs'),
        for (var i = 0; i < r.songs.length; i++)
          TrackTile(
            track: r.songs[i],
            onTap: () {
              _search(_query, save: true);
              handler.playTracks(r.songs, startIndex: i, context: 'search:$_query');
            },
          ),
      ],
      if (r.albums.isNotEmpty) ...[
        const SectionHeader('Albums'),
        for (final a in r.albums)
          ListTile(
            leading: ArtworkImage(url: a.artwork.thumb, icon: Icons.album),
            title: Text(a.title, maxLines: 1, overflow: TextOverflow.ellipsis),
            subtitle: Text('Album · ${a.artistNames}', maxLines: 1, overflow: TextOverflow.ellipsis),
            onTap: () => context.push('/album/${a.id}'),
          ),
      ],
      if (r.playlists.isNotEmpty) ...[
        const SectionHeader('Playlists'),
        for (final p in r.playlists)
          ListTile(
            leading: ArtworkImage(url: p.artwork.thumb, icon: Icons.queue_music),
            title: Text(p.title),
            subtitle: const Text('Playlist'),
            onTap: () => context.push('/playlist/${p.id}'),
          ),
      ],
      const SizedBox(height: 24),
    ]);
  }

  Widget _history() {
    final history = ref.watch(searchHistoryProvider);
    final items = history.value ?? const [];
    if (items.isEmpty) {
      return const EmptyView(icon: Icons.search, message: 'Search for songs, artists, albums and playlists');
    }
    return ListView(children: [
      SectionHeader('Recent searches',
          action: TextButton(
            onPressed: () async {
              await ref.read(musicRepositoryProvider).clearSearchHistory();
              ref.invalidate(searchHistoryProvider);
            },
            child: const Text('Clear'),
          )),
      for (final h in items)
        ListTile(
          leading: const Icon(Icons.history),
          title: Text(h['query'] as String),
          onTap: () {
            _controller.text = h['query'] as String;
            _search(_controller.text);
          },
        ),
    ]);
  }
}
