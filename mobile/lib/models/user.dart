import 'track.dart';
import 'catalog.dart';

class UserPreferences {
  const UserPreferences({this.languages = const [], this.audioQuality = 'high', this.allowExplicit = true});

  final List<String> languages;
  final String audioQuality;
  final bool allowExplicit;

  factory UserPreferences.fromJson(Map<String, dynamic> j) => UserPreferences(
        languages: (j['languages'] as List? ?? []).cast<String>(),
        audioQuality: j['audio_quality'] as String? ?? 'high',
        allowExplicit: j['allow_explicit'] as bool? ?? true,
      );

  Map<String, dynamic> toJson() => {'languages': languages, 'audio_quality': audioQuality, 'allow_explicit': allowExplicit};
}

/// This device's anonymous account.
class AppUser {
  const AppUser({required this.id, required this.displayName, required this.preferences});

  final String id;
  final String displayName;
  final UserPreferences preferences;

  factory AppUser.fromJson(Map<String, dynamic> j) => AppUser(
        id: j['id'] as String,
        displayName: j['display_name'] as String,
        preferences: UserPreferences.fromJson(j['preferences'] as Map<String, dynamic>? ?? {}),
      );

  Map<String, dynamic> toJson() => {
        'id': id,
        'display_name': displayName,
        'preferences': preferences.toJson(),
      };

  AppUser copyWith({String? displayName, UserPreferences? preferences}) => AppUser(
        id: id,
        displayName: displayName ?? this.displayName,
        preferences: preferences ?? this.preferences,
      );
}

class UserPlaylist {
  const UserPlaylist({
    required this.id,
    required this.name,
    this.description,
    this.isPublic = false,
    this.trackCount = 0,
    this.artwork = const [],
    this.tracks = const [],
  });

  final String id;
  final String name;
  final String? description;
  final bool isPublic;
  final int trackCount;
  final List<String> artwork;
  final List<Track> tracks;

  factory UserPlaylist.fromJson(Map<String, dynamic> j) => UserPlaylist(
        id: j['id'] as String,
        name: j['name'] as String,
        description: j['description'] as String?,
        isPublic: j['is_public'] as bool? ?? false,
        trackCount: (j['track_count'] as num?)?.toInt() ?? 0,
        artwork: (j['artwork'] as List? ?? []).cast<String>(),
        tracks: (j['tracks'] as List? ?? [])
            .map((e) => Track.fromJson((e as Map<String, dynamic>)['track'] as Map<String, dynamic>))
            .toList(),
      );
}

class FollowedArtist {
  const FollowedArtist(this.artist);
  final ArtistSummary artist;
}

class Recommendations {
  const Recommendations({required this.personalized, this.message, this.items = const []});

  final bool personalized;
  final String? message;
  final List<({Track track, String reason})> items;

  factory Recommendations.fromJson(Map<String, dynamic> j) => Recommendations(
        personalized: j['personalized'] as bool,
        message: j['message'] as String?,
        items: (j['items'] as List? ?? [])
            .map((e) => (
                  track: Track.fromJson((e as Map<String, dynamic>)['track'] as Map<String, dynamic>),
                  reason: e['reason'] as String,
                ))
            .toList(),
      );
}
