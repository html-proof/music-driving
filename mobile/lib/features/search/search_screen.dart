import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/config/app_config.dart';
import '../../core/errors/app_exception.dart';
import '../../core/theme/app_theme.dart';
import '../../models/catalog.dart';
import '../../models/track.dart';
import '../../providers/core_providers.dart';
import '../../widgets/common.dart';
import '../../widgets/track_tile.dart';

final searchHistoryProvider = FutureProvider<List<Map<String, dynamic>>>(
  (ref) async {
    try {
      return await ref.read(musicRepositoryProvider).searchHistory();
    } on AppException {
      return const [];
    }
  },
  retry: (_, _) => null,
);

/// Search categories, in chip order (the source has no podcasts).
const searchTabs = {'all': 'All', 'songs': 'Songs', 'artists': 'Artists', 'albums': 'Albums', 'playlists': 'Playlists'};

/// Trimmed, with runs of whitespace collapsed to one space.
String cleanSearchQuery(String raw) => raw.trim().replaceAll(RegExp(r'\s+'), ' ');

/// Latin queries need two characters before they are worth searching; one character of
/// another script (Malayalam, Devanagari, CJK, ...) is already a syllable or a word.
bool isSearchableQuery(String q) {
  if (q.isEmpty) return false;
  return q.runes.any((r) => r > 0x7f) || q.runes.length >= 2;
}

class SearchScreen extends ConsumerStatefulWidget {
  const SearchScreen({super.key});
  @override
  ConsumerState<SearchScreen> createState() => _SearchScreenState();
}

class _SearchScreenState extends ConsumerState<SearchScreen> {
  static const _maxPage = 20;

  final _controller = TextEditingController();
  Timer? _debounce;
  CancelToken? _cancel;

  /// Bumped by every new search; a response is only applied while its id is current,
  /// so a slow earlier response can never replace a newer one.
  int _requestId = 0;
  String _query = '';
  String _type = 'all';
  bool _loading = false;
  Object? _error;
  SearchResults? _results;
  String? _resultsType;
  bool _hasMore = false;
  bool _loadingMore = false;
  Object? _moreError;

  int _limitFor(String type) => type == 'all' ? 10 : 20;

  void _onChanged(String value) {
    _debounce?.cancel();
    if (cleanSearchQuery(value).isEmpty) {
      _search('');
      return;
    }
    _debounce = Timer(AppConfig.searchDebounce, () => _search(value));
  }

  void _searchNow(String value) {
    _debounce?.cancel();
    _search(value);
  }

  Future<void> _search(String raw) async {
    final q = cleanSearchQuery(raw);
    final id = ++_requestId;
    _cancel?.cancel(); // drop the previous in-flight request
    _cancel = null;
    if (!isSearchableQuery(q)) {
      setState(() {
        _query = '';
        _results = null;
        _error = null;
        _loading = false;
        _loadingMore = false;
        _moreError = null;
      });
      return;
    }
    final type = _type;
    final token = _cancel = CancelToken();
    setState(() {
      _query = q;
      _loading = true;
      _error = null;
      _loadingMore = false;
      _moreError = null;
    });
    try {
      final r = await ref
          .read(musicRepositoryProvider)
          .search(q, type: type, page: 1, limit: _limitFor(type), cancelToken: token);
      if (!mounted || id != _requestId) return;
      setState(() {
        _results = r;
        _resultsType = type;
        _hasMore = type != 'all' && r.hasMoreFor(type);
        _loading = false;
      });
    } catch (e) {
      if (!mounted || id != _requestId) return;
      setState(() {
        _error = e;
        _loading = false;
      });
    }
  }

  /// Next page of the open category, appended to what is shown. Scrolling near the end
  /// asks for it; after a failed page only the "Try again" button ([manual]) asks again,
  /// so scroll events never turn into a stream of retries against a failing provider.
  Future<void> _loadMore({bool manual = false}) async {
    final current = _results;
    final type = _type;
    if (current == null || type == 'all' || _resultsType != type || _loading || _loadingMore || !_hasMore) return;
    if (!manual && _moreError != null) return;
    final id = _requestId;
    final token = _cancel = CancelToken();
    setState(() {
      _loadingMore = true;
      _moreError = null;
    });
    try {
      final next = await ref
          .read(musicRepositoryProvider)
          .search(_query, type: type, page: current.page + 1, limit: _limitFor(type), cancelToken: token);
      if (!mounted || id != _requestId) return;
      final failed = next.errors[type];
      if (failed != null && next.countOf(type) == 0) {
        setState(() {
          _moreError = failed;
          _loadingMore = false;
        });
        return;
      }
      final merged = current.append(next);
      setState(() {
        _results = merged;
        // Stop when the source says so, at the last page, or when a page adds nothing new.
        _hasMore = next.hasMoreFor(type) && next.page < _maxPage && merged.countOf(type) > current.countOf(type);
        _loadingMore = false;
      });
    } catch (e) {
      if (!mounted || id != _requestId) return;
      setState(() {
        _moreError = e;
        _loadingMore = false;
      });
    }
  }

  void _selectType(String type) {
    if (type == _type) return;
    setState(() => _type = type);
    _searchNow(_controller.text);
  }

  /// Remember this query in the user's recent searches (the search itself is not re-run).
  void _record() {
    final q = _query;
    if (q.isEmpty) return;
    unawaited(ref.read(musicRepositoryProvider).recordSearch(q).then((_) {
      if (mounted) ref.invalidate(searchHistoryProvider);
    }));
  }

  void _playFrom(List<Track> visible, int index) {
    ref.read(audioHandlerProvider).playTracks(visible, startIndex: index, context: 'search:$_query');
    _record();
  }

  void _open(String location) {
    _record();
    context.push(location);
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
                        tooltip: 'Clear',
                        onPressed: () {
                          _controller.clear();
                          _searchNow('');
                        },
                      ),
              ),
              onChanged: (v) {
                setState(() {});
                _onChanged(v);
              },
              onSubmitted: _searchNow,
            ),
          ),
          if (_query.isNotEmpty) _chips(),
          Expanded(child: _body()),
        ]),
      ),
    );
  }

  Widget _chips() {
    return SizedBox(
      height: 48,
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
        children: [
          for (final e in searchTabs.entries)
            Padding(
              padding: const EdgeInsets.only(right: 8),
              child: ChoiceChip(
                key: ValueKey('search-tab-${e.key}'),
                label: Text(e.value),
                selected: _type == e.key,
                showCheckmark: false,
                onSelected: (_) => _selectType(e.key),
              ),
            ),
        ],
      ),
    );
  }

  Widget _body() {
    if (_query.isEmpty) return _history();
    final r = _resultsType == _type ? _results : null;
    if (_error != null) return ErrorView(error: _error!, onRetry: () => _searchNow(_query));
    if (r == null) return loadingView;
    final queryError = r.errors['query'];
    if (queryError != null) return EmptyView(icon: Icons.search_off, message: queryError);
    return _type == 'all' ? _allResults(r) : _categoryResults(r, _type);
  }

  List<Widget> _banners(SearchResults r) => [
        if (_loading) const LinearProgressIndicator(minHeight: 2),
        if (r.altQuery != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
            child: Text('Showing results for "${r.altQuery}" too',
                style: const TextStyle(color: AppColors.textSecondary, fontSize: 13)),
          ),
      ];

  Widget _allResults(SearchResults r) {
    if (r.isEmpty) {
      return r.errors.isNotEmpty
          ? ErrorView(error: r.errors.values.first, onRetry: () => _searchNow(_query))
          : EmptyView(icon: Icons.search_off, message: 'No results for "$_query"');
    }
    const shown = {'artists': 4, 'songs': 5, 'albums': 6, 'playlists': 6};
    final songs = r.songs.take(shown['songs']!).toList();
    Widget header(String section) {
      final more = r.countOf(section) > shown[section]! || r.hasMoreFor(section);
      return SectionHeader(
        searchTabs[section]!,
        action: more
            ? TextButton(
                key: ValueKey('see-all-$section'),
                onPressed: () => _selectType(section),
                child: const Text('See all'),
              )
            : null,
      );
    }

    final children = <Widget>[..._banners(r)];
    for (final section in const ['artists', 'songs', 'albums', 'playlists']) {
      final failed = r.errors[section];
      if (r.countOf(section) == 0) {
        if (failed != null) children.add(_SectionError(title: searchTabs[section]!, message: failed, onRetry: () => _searchNow(_query)));
        continue;
      }
      children.add(header(section));
      switch (section) {
        case 'artists':
          children.addAll(r.artists.take(shown[section]!).map(_artistTile));
        case 'songs':
          for (var i = 0; i < songs.length; i++) {
            children.add(_songTile(songs, i));
          }
        case 'albums':
          children.addAll(r.albums.take(shown[section]!).map(_albumTile));
        case 'playlists':
          children.addAll(r.playlists.take(shown[section]!).map(_playlistTile));
      }
    }
    children.add(const SizedBox(height: 24));
    return ListView(children: children);
  }

  Widget _categoryResults(SearchResults r, String type) {
    final count = r.countOf(type);
    if (count == 0) {
      final failed = r.errors[type];
      return failed != null
          ? ErrorView(error: failed, onRetry: () => _searchNow(_query))
          : EmptyView(icon: Icons.search_off, message: 'No ${searchTabs[type]!.toLowerCase()} found for "$_query"');
    }
    final banners = _banners(r);
    final songs = r.songs;
    return NotificationListener<ScrollNotification>(
      onNotification: (n) {
        if (n.metrics.extentAfter < 400) _loadMore();
        return false;
      },
      child: ListView.builder(
        itemCount: banners.length + count + 1,
        itemBuilder: (_, i) {
          if (i < banners.length) return banners[i];
          final row = i - banners.length;
          if (row == count) return _footer();
          return switch (type) {
            'songs' => _songTile(songs, row),
            'artists' => _artistTile(r.artists[row]),
            'albums' => _albumTile(r.albums[row]),
            _ => _playlistTile(r.playlists[row]),
          };
        },
      ),
    );
  }

  Widget _footer() {
    if (_loadingMore) {
      return const Padding(padding: EdgeInsets.all(16), child: Center(child: CircularProgressIndicator()));
    }
    if (_moreError != null) {
      return Padding(
        padding: const EdgeInsets.all(16),
        child: Column(children: [
          Text(AppException.from(_moreError!).message,
              textAlign: TextAlign.center, style: const TextStyle(color: AppColors.textSecondary)),
          TextButton(onPressed: () => _loadMore(manual: true), child: const Text('Try again')),
        ]),
      );
    }
    if (_hasMore) {
      return Center(child: TextButton(onPressed: () => _loadMore(manual: true), child: const Text('Load more')));
    }
    return const SizedBox(height: 24);
  }

  Widget _songTile(List<Track> visible, int i) => TrackTile(
        track: visible[i],
        typeLabel: 'Song',
        showDuration: true,
        onTap: () => _playFrom(visible, i),
      );

  Widget _artistTile(ArtistSummary a) => ListTile(
        leading: ArtworkImage(url: a.artwork.thumb, circle: true, icon: Icons.person),
        title: Text(a.name, maxLines: 1, overflow: TextOverflow.ellipsis),
        subtitle: const Text('Artist'),
        onTap: () => _open('/artist/${a.id}'),
      );

  Widget _albumTile(AlbumSummary a) => ListTile(
        leading: ArtworkImage(url: a.artwork.thumb, icon: Icons.album),
        title: Text(a.title, maxLines: 1, overflow: TextOverflow.ellipsis),
        subtitle: Text(a.artists.isEmpty ? 'Album' : 'Album · ${a.artistNames}',
            maxLines: 1, overflow: TextOverflow.ellipsis),
        onTap: () => _open('/album/${a.id}'),
      );

  Widget _playlistTile(PlaylistSummary p) => ListTile(
        leading: ArtworkImage(url: p.artwork.thumb, icon: Icons.queue_music),
        title: Text(p.title, maxLines: 1, overflow: TextOverflow.ellipsis),
        subtitle: Text(p.language == null ? 'Playlist' : 'Playlist · ${p.language}'),
        onTap: () => _open('/playlist/${p.id}'),
      );

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
            _searchNow(_controller.text);
          },
        ),
    ]);
  }
}

/// A search section the provider couldn't answer, with its own retry.
class _SectionError extends StatelessWidget {
  const _SectionError({required this.title, required this.message, required this.onRetry});

  final String title;
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 16, 8, 0),
      child: Row(children: [
        const Icon(Icons.error_outline, size: 18, color: AppColors.textSecondary),
        const SizedBox(width: 8),
        Expanded(
          child: Text('$title couldn\'t load: $message',
              maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(color: AppColors.textSecondary)),
        ),
        TextButton(onPressed: onRetry, child: const Text('Retry')),
      ]),
    );
  }
}
