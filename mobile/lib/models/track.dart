class Artwork {
  const Artwork({this.small, this.medium, this.large});

  final String? small;
  final String? medium;
  final String? large;

  factory Artwork.fromJson(Map<String, dynamic>? json) => Artwork(
        small: json?['small'] as String?,
        medium: json?['medium'] as String?,
        large: json?['large'] as String?,
      );

  Map<String, dynamic> toJson() => {'small': small, 'medium': medium, 'large': large};

  String? get best => large ?? medium ?? small;
  String? get thumb => small ?? medium ?? large;
}

class ArtistRef {
  const ArtistRef({required this.name, this.id, this.numericId});

  final String name;
  final String? id;
  final String? numericId;

  factory ArtistRef.fromJson(Map<String, dynamic> json) => ArtistRef(
        name: json['name'] as String,
        id: json['id'] as String?,
        numericId: json['numeric_id'] as String?,
      );

  Map<String, dynamic> toJson() => {'name': name, 'id': id, 'numeric_id': numericId};
}

class AlbumRef {
  const AlbumRef({required this.title, this.id, this.numericId});

  final String title;
  final String? id;
  final String? numericId;

  factory AlbumRef.fromJson(Map<String, dynamic> json) => AlbumRef(
        title: json['title'] as String,
        id: json['id'] as String?,
        numericId: json['numeric_id'] as String?,
      );

  Map<String, dynamic> toJson() => {'title': title, 'id': id, 'numeric_id': numericId};
}

/// A song from the provider catalogue. `id` is the provider seokey.
class Track {
  const Track({
    required this.id,
    required this.title,
    this.trackId,
    this.artists = const [],
    this.album,
    this.duration = 0,
    this.language,
    this.genres = const [],
    this.isExplicit = false,
    this.releaseDate,
    this.artwork = const Artwork(),
    this.playable = true,
  });

  final String id;
  final String? trackId;
  final String title;
  final List<ArtistRef> artists;
  final AlbumRef? album;
  /// Seconds; 0 means unknown (search/list rows often carry no duration), never 0:00.
  final int duration;
  final String? language;
  final List<String> genres;
  final bool isExplicit;
  final String? releaseDate;
  final Artwork artwork;
  final bool playable;

  String get artistNames => artists.map((a) => a.name).join(', ');
  Duration get durationValue => Duration(seconds: duration);
  bool get hasDuration => duration > 0;

  factory Track.fromJson(Map<String, dynamic> json) => Track(
        id: json['id'] as String,
        trackId: json['track_id'] as String?,
        title: json['title'] as String,
        artists: (json['artists'] as List? ?? [])
            .map((e) => ArtistRef.fromJson(e as Map<String, dynamic>))
            .toList(),
        album: json['album'] == null ? null : AlbumRef.fromJson(json['album'] as Map<String, dynamic>),
        duration: (json['duration'] as num?)?.toInt() ?? 0,
        language: json['language'] as String?,
        genres: (json['genres'] as List? ?? []).cast<String>(),
        isExplicit: json['is_explicit'] as bool? ?? false,
        releaseDate: json['release_date'] as String?,
        artwork: Artwork.fromJson(json['artwork'] as Map<String, dynamic>?),
        playable: json['playable'] as bool? ?? true,
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'track_id': trackId,
        'title': title,
        'artists': artists.map((a) => a.toJson()).toList(),
        'album': album?.toJson(),
        'duration': duration,
        'language': language,
        'genres': genres,
        'is_explicit': isExplicit,
        'release_date': releaseDate,
        'artwork': artwork.toJson(),
        'playable': playable,
      };

  @override
  bool operator ==(Object other) => other is Track && other.id == id;

  @override
  int get hashCode => id.hashCode;
}

List<Track> tracksFrom(dynamic list) =>
    (list as List? ?? []).map((e) => Track.fromJson(e as Map<String, dynamic>)).toList();
