// On-device test harness for the playback stack. NOT part of the app build.
//
// Runs the production MelodiaAudioHandler + just_audio + audio_service (same
// AudioServiceConfig, same MediaSession, notification and media-button handling) against
// local test tones served from the development machine, so lock screen, notification,
// Bluetooth/headset buttons and the Previous rule can be verified on real hardware even
// when the music provider is unreachable. Every state change is logged with a
// "HARNESS" prefix for `adb logcat`.
//
//   python tool/make_harness_media.py <dir> && python -m http.server 8765 -d <dir>
//   adb reverse tcp:8765 tcp:8765
//   flutter run -t tool/media_session_harness.dart
import 'dart:async';

import 'package:audio_service/audio_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:just_audio/just_audio.dart';
import 'package:melodia/core/theme/app_theme.dart';
import 'package:melodia/features/lyrics/lyrics_view.dart';
import 'package:melodia/features/player/audio_engine.dart';
import 'package:melodia/features/player/audio_handler.dart';
import 'package:melodia/features/player/audio_service_config.dart';
import 'package:melodia/features/player/player_providers.dart';
import 'package:melodia/features/player/widgets/player_controls.dart';
import 'package:melodia/features/player/widgets/seek_bar.dart';
import 'package:melodia/models/catalog.dart';
import 'package:melodia/models/track.dart';
import 'package:melodia/providers/core_providers.dart';

const _host = 'http://127.0.0.1:8765';

final _tracks = [
  for (final (id, title, artist) in [
    ('tone-a', 'Harness Tone A', 'Test Artist One'),
    ('tone-b', 'Harness Tone B', 'Test Artist Two'),
    ('tone-c', 'Harness Tone C', 'Test Artist Three'),
  ])
    Track(
      id: id,
      title: title,
      artists: [ArtistRef(name: artist)],
      album: const AlbumRef(title: 'Harness Album'),
      duration: 40,
      artwork: Artwork(large: '$_host/$id.png', small: '$_host/$id.png'),
    ),
];

/// Clearly-labelled test lyrics for the test tones (one line every 3 s).
Lyrics _harnessLyrics(String id) => Lyrics(
      songId: id,
      available: true,
      synced: true,
      source: 'harness',
      lines: [for (var i = 0; i < 13; i++) LyricLine(Duration(seconds: 1 + i * 3), '$id line ${i + 1} @ ${1 + i * 3}s')],
    );

class _NoReporter implements PlaybackReporter {
  @override
  Future<void> complete(String songId, double secondsListened, {required bool completed, String? context}) async {}
  @override
  Future<void> progress(String songId, double positionSeconds, int index) async {}
  @override
  Future<void> syncSession({
    required List<String> queue,
    required int currentIndex,
    required double positionSeconds,
    required bool shuffle,
    required String repeatMode,
    required String quality,
    String? context,
  }) async {}
}

class _MemoryStore implements QueueStore {
  Map<String, dynamic>? _data;
  @override
  Future<Map<String, dynamic>?> load() async => _data;
  @override
  Future<void> save(Map<String, dynamic> state) async => _data = state;
}

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final handler = await AudioService.init(
    builder: () => MelodiaAudioHandler(
      engine: JustAudioEngine(null, (uri) => AudioSource.uri(uri)),
      resolveStream: (id, q) async => StreamInfo(
        url: '$_host/$id.wav',
        quality: q,
        bitrateKbps: 1411,
        expiresAt: DateTime.now().toUtc().add(const Duration(hours: 4)),
      ),
      reporter: _NoReporter(),
      store: _MemoryStore(),
    ),
    config: melodiaAudioServiceConfig,
  );
  await handler.init();

  handler.mediaItem.listen((m) => debugPrint('HARNESS item id=${m?.id} title=${m?.title} artist=${m?.artist} art=${m?.artUri}'));
  String? last;
  handler.playbackState.listen((s) {
    final line = 'HARNESS state status=${playerStatusOf(s).name} index=${s.queueIndex} '
        'repeat=${s.repeatMode.name} shuffle=${s.shuffleMode.name}';
    if (line != last) debugPrint('$line pos=${handler.displayPosition.inMilliseconds}');
    last = line;
  });
  Timer.periodic(const Duration(seconds: 1), (_) {
    if (handler.currentTrack == null) return;
    debugPrint('HARNESS tick id=${handler.currentTrack!.id} pos=${handler.displayPosition.inMilliseconds} '
        'playing=${handler.playbackState.value.playing}');
  });

  runApp(ProviderScope(
    overrides: [
      audioHandlerProvider.overrideWithValue(handler),
      for (final t in _tracks) lyricsProvider(t.id).overrideWith((ref) async => _harnessLyrics(t.id)),
    ],
    child: MaterialApp(theme: buildDarkTheme(), home: const _HarnessScreen()),
  ));
}

class _HarnessScreen extends ConsumerWidget {
  const _HarnessScreen();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final track = ref.watch(currentTrackProvider);
    final status = ref.watch(playerStatusProvider);
    return Scaffold(
      appBar: AppBar(title: const Text('Media session harness')),
      body: SafeArea(
        child: Column(children: [
          FilledButton(
            key: const Key('start'),
            onPressed: () => ref.read(audioHandlerProvider).playTracks(_tracks, startIndex: 1, context: 'harness:Test queue'),
            child: const Text('Play test queue (starts at B)'),
          ),
          const SizedBox(height: 8),
          Text(track == null ? 'Nothing playing' : '${track.title} — ${track.artistNames}',
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.bold)),
          Text('status: ${status.name}'),
          Expanded(child: track == null ? const SizedBox() : LyricsPanel(track: track)),
          const SeekBar(),
          const PlayerControls(),
          const SizedBox(height: 12),
        ]),
      ),
    );
  }
}
