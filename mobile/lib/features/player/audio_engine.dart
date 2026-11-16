import 'dart:async';

import 'package:just_audio/just_audio.dart';

enum EngineState { idle, loading, buffering, ready, completed }

/// The minimal surface of the audio player the handler needs. Production uses
/// [JustAudioEngine]; tests use a fake so queue/control logic runs without a device.
abstract class AudioEngine {
  Stream<Duration> get positionStream;
  Stream<Duration> get bufferedPositionStream;
  Stream<Duration?> get durationStream;
  Stream<bool> get playingStream;
  Stream<EngineState> get stateStream;

  /// Errors raised while playing (network drop, expired URL...).
  Stream<Object> get errorStream;

  Duration get position;
  Duration get bufferedPosition;
  Duration? get duration;
  bool get playing;
  double get speed;
  EngineState get state;

  Future<Duration?> setUrl(String url, {Duration? initialPosition});
  Future<void> play();
  Future<void> pause();
  Future<void> seek(Duration position);
  Future<void> stop();
  Future<void> setVolume(double volume);
  Future<void> setSpeed(double speed);
  Future<void> dispose();
}

class JustAudioEngine implements AudioEngine {
  // handleInterruptions: false — MelodiaAudioHandler owns interruption, ducking and
  // "becoming noisy" handling. Leaving just_audio's own handling on would react to every
  // phone call / unplug twice and could resume audio the handler decided to keep paused.
  JustAudioEngine([AudioPlayer? player]) : _player = player ?? AudioPlayer(handleInterruptions: false) {
    _player.errorStream.listen(_errors.add);
  }

  final AudioPlayer _player;
  final _errors = StreamController<Object>.broadcast();

  static EngineState _map(ProcessingState s) => switch (s) {
        ProcessingState.idle => EngineState.idle,
        ProcessingState.loading => EngineState.loading,
        ProcessingState.buffering => EngineState.buffering,
        ProcessingState.ready => EngineState.ready,
        ProcessingState.completed => EngineState.completed,
      };

  @override
  Stream<Duration> get positionStream => _player.positionStream;
  @override
  Stream<Duration> get bufferedPositionStream => _player.bufferedPositionStream;
  @override
  Stream<Duration?> get durationStream => _player.durationStream;
  @override
  Stream<bool> get playingStream => _player.playingStream;
  @override
  Stream<EngineState> get stateStream => _player.processingStateStream.map(_map);
  @override
  Stream<Object> get errorStream => _errors.stream;

  @override
  Duration get position => _player.position;
  @override
  Duration get bufferedPosition => _player.bufferedPosition;
  @override
  Duration? get duration => _player.duration;
  @override
  bool get playing => _player.playing;
  @override
  double get speed => _player.speed;
  @override
  EngineState get state => _map(_player.processingState);

  @override
  Future<Duration?> setUrl(String url, {Duration? initialPosition}) =>
      // Provider streams are HLS (.m3u8); declare it explicitly so detection never
      // depends on the URL's query string.
      _player.setAudioSource(HlsAudioSource(Uri.parse(url)), initialPosition: initialPosition);

  @override
  Future<void> play() async {
    // just_audio's play() completes only when playback pauses/stops; don't await it.
    unawaited(_player.play());
  }

  @override
  Future<void> pause() => _player.pause();
  @override
  Future<void> seek(Duration position) => _player.seek(position);
  @override
  Future<void> stop() => _player.stop();
  @override
  Future<void> setVolume(double volume) => _player.setVolume(volume);
  @override
  Future<void> setSpeed(double speed) => _player.setSpeed(speed);
  @override
  Future<void> dispose() async {
    await _errors.close();
    await _player.dispose();
  }
}
