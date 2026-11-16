import 'track.dart';

class AlbumSummary {
  const AlbumSummary({
    required this.id,
    required this.title,
    this.numericId,
    this.artists = const [],
    this.artwork = const Artwork(),
    this.releaseDate,
    this.trackCount,
  });

  final String id;
  final String? numericId;
  final String title;
  final List<ArtistRef> artists;
  final Artwork artwork;
  final String? releaseDate;
  final int? trackCount;

  String get artistNames => artists.map((a) => a.name).join(', ');

  factory AlbumSummary.fromJson(Map<String, dynamic> j) => AlbumSummary(
        id: j['id'] as String,
        numericId: j['numeric_id'] as String?,
        title: j['title'] as String,
        artists: (j['artists'] as List? ?? []).map((e) => ArtistRef.fromJson(e as Map<String, dynamic>)).toList(),
        artwork: Artwork.fromJson(j['artwork'] as Map<String, dynamic>?),
        releaseDate: j['release_date'] as String?,
        trackCount: (j['track_count'] as num?)?.toInt(),
      );
}

class AlbumDetail extends AlbumSummary {
  const AlbumDetail({
    required super.id,
    required super.title,
    super.numericId,
    super.artists,
    super.artwork,
    super.releaseDate,
    super.trackCount,
    this.label,
    this.tracks = const [],
  });

  final String? label;
  final List<Track> tracks;

  factory AlbumDetail.fromJson(Map<String, dynamic> j) {
    final s = AlbumSummary.fromJson(j);
    return AlbumDetail(
      id: s.id,
      title: s.title,
      numericId: s.numericId,
      artists: s.artists,
      artwork: s.artwork,
      releaseDate: s.releaseDate,
      trackCount: s.trackCount,
      label: j['label'] as String?,
      tracks: tracksFrom(j['tracks']),
    );
  }
}

class ArtistSummary {
  const ArtistSummary({required this.id, required this.name, this.numericId, this.artwork = const Artwork(), this.followerCount});

  final String id;
  final String? numericId;
  final String name;
  final Artwork artwork;
  final int? followerCount;

  factory ArtistSummary.fromJson(Map<String, dynamic> j) => ArtistSummary(
        id: j['id'] as String,
        numericId: j['numeric_id'] as String?,
        name: j['name'] as String,
        artwork: Artwork.fromJson(j['artwork'] as Map<String, dynamic>?),
        followerCount: (j['follower_count'] as num?)?.toInt(),
      );
}

class ArtistDetail extends ArtistSummary {
  const ArtistDetail({
    required super.id,
    required super.name,
    super.numericId,
    super.artwork,
    super.followerCount,
    this.topTracks = const [],
    this.similarArtists = const [],
    this.isFollowed = false,
  });

  final List<Track> topTracks;
  final List<ArtistSummary> similarArtists;
  final bool isFollowed;

  factory ArtistDetail.fromJson(Map<String, dynamic> j) {
    final s = ArtistSummary.fromJson(j);
    return ArtistDetail(
      id: s.id,
      name: s.name,
      numericId: s.numericId,
      artwork: s.artwork,
      followerCount: s.followerCount,
      topTracks: tracksFrom(j['top_tracks']),
      similarArtists: (j['similar_artists'] as List? ?? [])
          .map((e) => ArtistSummary.fromJson(e as Map<String, dynamic>))
          .toList(),
      isFollowed: j['is_followed'] as bool? ?? false,
    );
  }
}

class PlaylistSummary {
  const PlaylistSummary({required this.id, required this.title, this.artwork = const Artwork(), this.language, this.playCount});

  final String id;
  final String title;
  final Artwork artwork;
  final String? language;
  final String? playCount;

  factory PlaylistSummary.fromJson(Map<String, dynamic> j) => PlaylistSummary(
        id: j['id'] as String,
        title: j['title'] as String,
        artwork: Artwork.fromJson(j['artwork'] as Map<String, dynamic>?),
        language: j['language'] as String?,
        playCount: j['play_count'] as String?,
      );
}

class PlaylistDetail extends PlaylistSummary {
  const PlaylistDetail({required super.id, required super.title, super.artwork, super.language, this.tracks = const []});

  final List<Track> tracks;

  factory PlaylistDetail.fromJson(Map<String, dynamic> j) {
    final s = PlaylistSummary.fromJson(j);
    return PlaylistDetail(id: s.id, title: s.title, artwork: s.artwork, language: s.language, tracks: tracksFrom(j['tracks']));
  }
}

class HomeSection {
  const HomeSection({
    required this.id,
    required this.title,
    required this.type,
    this.subtitle,
    this.tracks = const [],
    this.albums = const [],
    this.artists = const [],
    this.playlists = const [],
  });

  final String id;
  final String title;
  final String? subtitle;
  final String type; // tracks | albums | artists | playlists
  final List<Track> tracks;
  final List<AlbumSummary> albums;
  final List<ArtistSummary> artists;
  final List<PlaylistSummary> playlists;

  factory HomeSection.fromJson(Map<String, dynamic> j) => HomeSection(
        id: j['id'] as String,
        title: j['title'] as String,
        subtitle: j['subtitle'] as String?,
        type: j['type'] as String,
        tracks: tracksFrom(j['tracks']),
        albums: (j['albums'] as List? ?? []).map((e) => AlbumSummary.fromJson(e as Map<String, dynamic>)).toList(),
        artists: (j['artists'] as List? ?? []).map((e) => ArtistSummary.fromJson(e as Map<String, dynamic>)).toList(),
        playlists:
            (j['playlists'] as List? ?? []).map((e) => PlaylistSummary.fromJson(e as Map<String, dynamic>)).toList(),
      );
}

class HomeFeed {
  const HomeFeed({
    required this.greeting,
    required this.sections,
    this.errors = const {},
    this.unavailableLanguages = const [],
    this.fromCache = false,
  });

  final String greeting;
  final List<HomeSection> sections;
  final Map<String, String> errors;

  /// Languages whose songs the music provider couldn't return right now.
  final List<String> unavailableLanguages;
  final bool fromCache;

  factory HomeFeed.fromJson(Map<String, dynamic> j, {bool fromCache = false}) => HomeFeed(
        greeting: j['greeting'] as String,
        sections: (j['sections'] as List).map((e) => HomeSection.fromJson(e as Map<String, dynamic>)).toList(),
        errors: (j['errors'] as Map? ?? {}).cast<String, String>(),
        unavailableLanguages: (j['unavailable_languages'] as List? ?? const []).cast<String>(),
        fromCache: fromCache,
      );
}

class SearchResults {
  const SearchResults({
    this.songs = const [],
    this.albums = const [],
    this.artists = const [],
    this.playlists = const [],
    this.errors = const {},
  });

  final List<Track> songs;
  final List<AlbumSummary> albums;
  final List<ArtistSummary> artists;
  final List<PlaylistSummary> playlists;
  final Map<String, String> errors;

  bool get isEmpty => songs.isEmpty && albums.isEmpty && artists.isEmpty && playlists.isEmpty;

  factory SearchResults.fromJson(Map<String, dynamic> j) => SearchResults(
        songs: tracksFrom(j['songs']),
        albums: (j['albums'] as List? ?? []).map((e) => AlbumSummary.fromJson(e as Map<String, dynamic>)).toList(),
        artists: (j['artists'] as List? ?? []).map((e) => ArtistSummary.fromJson(e as Map<String, dynamic>)).toList(),
        playlists:
            (j['playlists'] as List? ?? []).map((e) => PlaylistSummary.fromJson(e as Map<String, dynamic>)).toList(),
        errors: (j['errors'] as Map? ?? {}).cast<String, String>(),
      );
}

class StreamInfo {
  const StreamInfo({required this.url, required this.quality, required this.bitrateKbps, this.expiresAt, this.availableQualities = const [], this.format = 'hls'});

  final String url;
  final String quality;
  final int bitrateKbps;
  final DateTime? expiresAt;
  final List<String> availableQualities;

  /// `hls` (Gaana) or a progressive file type such as `mp3` (Audius).
  final String format;

  bool get isHls => format == 'hls';

  /// Treat a URL as stale two minutes before the provider token expires.
  bool get isStale => expiresAt != null && DateTime.now().toUtc().isAfter(expiresAt!.subtract(const Duration(minutes: 2)));

  factory StreamInfo.fromJson(Map<String, dynamic> j) => StreamInfo(
        url: j['url'] as String,
        quality: j['quality'] as String,
        bitrateKbps: (j['bitrate_kbps'] as num).toInt(),
        expiresAt: j['expires_at'] == null ? null : DateTime.parse(j['expires_at'] as String).toUtc(),
        availableQualities: (j['available_qualities'] as List? ?? []).cast<String>(),
        format: j['format'] as String? ?? 'hls',
      );
}

class LyricLine {
  const LyricLine(this.time, this.text);
  final Duration time;
  final String text;
}

class Lyrics {
  const Lyrics({
    required this.available,
    required this.synced,
    this.lines = const [],
    this.plainText,
    this.instrumental = false,
    this.songId,
    this.source,
  });

  /// The catalogue song these lyrics were matched to (server-side, by title, artist,
  /// album and duration). The UI refuses to show lyrics for any other song.
  final String? songId;
  final String? source;
  final bool available;
  final bool synced;
  final bool instrumental;
  final List<LyricLine> lines;
  final String? plainText;

  factory Lyrics.fromJson(Map<String, dynamic> j) => Lyrics(
        songId: j['song_id'] as String?,
        source: j['source'] as String?,
        available: j['available'] as bool,
        synced: j['synced'] as bool,
        instrumental: j['instrumental'] as bool? ?? false,
        plainText: j['plain_text'] as String?,
        lines: (j['lines'] as List? ?? [])
            .map((e) => LyricLine(Duration(milliseconds: (e['time_ms'] as num).toInt()), e['text'] as String))
            .toList()
          // Binary search below requires ascending timestamps.
          ..sort((a, b) => a.time.compareTo(b.time)),
      );

  /// True when these lyrics may be shown for [trackId].
  bool belongsTo(String trackId) => songId == null || songId == trackId;

  /// Index of the line being sung at [position], or -1 before the first line.
  int lineIndexAt(Duration position) {
    var lo = 0, hi = lines.length - 1, found = -1;
    while (lo <= hi) {
      final mid = (lo + hi) >> 1;
      if (lines[mid].time <= position) {
        found = mid;
        lo = mid + 1;
      } else {
        hi = mid - 1;
      }
    }
    return found;
  }
}
