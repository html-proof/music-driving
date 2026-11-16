import 'dart:async';
import 'dart:convert';

import 'package:audio_service/audio_service.dart';
import 'package:audio_session/audio_session.dart';
import 'package:flutter/foundation.dart' show visibleForTesting;
import 'package:shared_preferences/shared_preferences.dart';

import '../../core/config/app_config.dart';
import '../../core/errors/app_exception.dart';
import '../../models/catalog.dart';
import '../../models/track.dart';
import 'audio_engine.dart';
import 'play_queue.dart';

typedef StreamResolver = Future<StreamInfo> Function(String songId, String quality);

/// Receives playback events for history and cross-device sync. Must never throw.
abstract class PlaybackReporter {
  Future<void> syncSession({
    required List<String> queue,
    required int currentIndex,
    required double positionSeconds,
    required bool shuffle,
    required String repeatMode,
    required String quality,
    String? context,
  });
  Future<void> progress(String songId, double positionSeconds, int index);
  Future<void> complete(String songId, double secondsListened, {required bool completed, String? context});
}

/// Persists the queue so playback state survives app restarts.
abstract class QueueStore {
  Future<Map<String, dynamic>?> load();
  Future<void> save(Map<String, dynamic> state);
}

class PrefsQueueStore implements QueueStore {
  PrefsQueueStore(this.prefs);
  final SharedPreferences prefs;
  static const _key = 'player_state_v1';

  @override
  Future<Map<String, dynamic>?> load() async {
    final raw = prefs.getString(_key);
    if (raw == null) return null;
    try {
      return jsonDecode(raw) as Map<String, dynamic>;
    } catch (_) {
      return null;
    }
  }

  @override
  Future<void> save(Map<String, dynamic> state) => prefs.setString(_key, jsonEncode(state));
}

MediaItem mediaItemFor(Track t) => MediaItem(
      id: t.id,
      title: t.title,
      artist: t.artistNames,
      album: t.album?.title,
      duration: t.duration > 0 ? t.durationValue : null,
      artUri: t.artwork.best == null ? null : Uri.tryParse(t.artwork.best!),
      extras: {'track': t.toJson()},
    );

/// The app's single playback engine. The full player, mini player, notification,
/// lock screen and Bluetooth/headset buttons all drive this one instance.
class MelodiaAudioHandler extends BaseAudioHandler with QueueHandler, SeekHandler {
  MelodiaAudioHandler({
    required AudioEngine engine,
    required StreamResolver resolveStream,
    required PlaybackReporter reporter,
    required QueueStore store,
    String quality = 'high',
    this.configureSession = true,
  })  : _engine = engine, // ignore: prefer_initializing_formals
        _resolve = resolveStream,
        _reporter = reporter, // ignore: prefer_initializing_formals
        _store = store, // ignore: prefer_initializing_formals
        _quality = quality { // ignore: prefer_initializing_formals
    _wireEngine();
    _broadcast();
  }

  final AudioEngine _engine;
  final StreamResolver _resolve;
  final PlaybackReporter _reporter;
  final QueueStore _store;
  final bool configureSession;

  final PlayQueue _queue = PlayQueue();
  final Map<String, StreamInfo> _streams = {};
  final _errors = StreamController<String>.broadcast();
  final _queueChanges = StreamController<void>.broadcast();

  String _quality;
  String? _context;
  int _loadGeneration = 0;
  bool _needsLoad = false;
  Duration? _pendingPosition;
  int _consecutiveFailures = 0;
  bool _recovering = false;
  bool _loading = false;
  bool _resumeAfterInterruption = false;
  double _listenedSeconds = 0;
  Duration _lastPosition = Duration.zero;
  String? _activeStreamQuality;
  String? _errorMessage;
  // Where the track being loaded starts. While a load is in flight the engine still
  // reports the *previous* source's position, which must never reach the UI, lyrics,
  // notification or the Previous-button rule.
  Duration _loadPosition = Duration.zero;
  Duration? _seekWhileLoading;
  // Whether the in-flight load should start playing; play/pause pressed during a load
  // change this instead of being lost.
  bool _playAfterLoad = false;
  String? _lastRecoveredTrackId;
  DateTime _lastRecoveryAt = DateTime.fromMillisecondsSinceEpoch(0);
  Timer? _persistTimer;
  Timer? _syncDebounce;
  DateTime _lastProgressReport = DateTime.fromMillisecondsSinceEpoch(0);

  /// User-facing playback problems (e.g. "Couldn't play X, skipping").
  Stream<String> get errors => _errors.stream;
  Stream<void> get queueChanges => _queueChanges.stream;
  Stream<Duration> get positionStream => _engine.positionStream;
  Stream<Duration> get bufferedPositionStream => _engine.bufferedPositionStream;
  Duration get position => _engine.position;

  /// Position of the *current* track as every control sees it: the restored position
  /// before the first load, the start/seek target while a track is loading, otherwise
  /// the audio engine's real position.
  Duration get displayPosition {
    if (_needsLoad) return _pendingPosition ?? Duration.zero;
    if (_loading) return _seekWhileLoading ?? _loadPosition;
    return _engine.position;
  }

  PlayQueue get playQueue => _queue;
  Track? get currentTrack => _queue.current;
  String get quality => _quality;
  String? get activeStreamQuality => _activeStreamQuality;
  String? get playContext => _context;

  /// Why the current song can't play (shown with the `error` processing state).
  String? get errorMessage => _errorMessage;

  // --- setup -------------------------------------------------------------------
  Future<void> init() async {
    if (configureSession) await _configureAudioSession();
    await _restore();
  }

  Future<void> _configureAudioSession() async {
    final session = await AudioSession.instance;
    // Android: USAGE_MEDIA + audio focus. iOS: AVAudioSessionCategoryPlayback (plays
    // with the silent switch on and in the background).
    await session.configure(const AudioSessionConfiguration.music());
    // Phone calls, other apps, navigation prompts (Android audio focus / iOS interruptions).
    session.interruptionEventStream.listen((e) => handleInterruption(begin: e.begin, type: e.type));
    // Headphones unplugged / Bluetooth disconnected.
    session.becomingNoisyEventStream.listen((_) => handleBecomingNoisy());
  }

  /// OS audio interruption. Resumes afterwards only when the OS says the interruption
  /// was transient AND we were playing when it started AND the user didn't press
  /// play/pause in between.
  @visibleForTesting
  Future<void> handleInterruption({required bool begin, required AudioInterruptionType type}) async {
    if (begin) {
      switch (type) {
        case AudioInterruptionType.duck:
          await _engine.setVolume(0.3);
        case AudioInterruptionType.pause:
        case AudioInterruptionType.unknown:
          // `unknown` = permanent focus loss (another music app): never auto-resume.
          final wasPlaying = _engine.playing || (_loading && _playAfterLoad);
          _resumeAfterInterruption = wasPlaying && type == AudioInterruptionType.pause;
          _playAfterLoad = false;
          await _engine.pause(); // not pause(): that would count as a user action
          _persist();
      }
    } else {
      switch (type) {
        case AudioInterruptionType.duck:
          await _engine.setVolume(1.0);
        case AudioInterruptionType.pause:
          final resume = _resumeAfterInterruption;
          _resumeAfterInterruption = false;
          if (resume) await play();
        case AudioInterruptionType.unknown:
          _resumeAfterInterruption = false;
      }
    }
  }

  /// Headphones unplugged / Bluetooth audio route lost: pause and stay paused.
  @visibleForTesting
  Future<void> handleBecomingNoisy() async {
    _resumeAfterInterruption = false;
    if (_engine.playing) await pause();
  }

  void _wireEngine() {
    _engine.playingStream.listen((_) => _broadcast());
    _engine.stateStream.listen((state) {
      _broadcast();
      if (state == EngineState.completed) _onCompleted();
    });
    _engine.durationStream.listen((d) {
      final item = mediaItem.value;
      if (d != null && item != null && item.duration != d) mediaItem.add(item.copyWith(duration: d));
    });
    _engine.positionStream.listen(_onPosition);
    _engine.errorStream.listen(_onEngineError);
  }

  // --- public API used by the UI ----------------------------------------------------
  Future<void> playTracks(List<Track> tracks, {int startIndex = 0, String? context, bool? shuffle}) async {
    final playable = tracks.where((t) => t.playable).toList();
    if (playable.isEmpty) {
      _errors.add('None of these songs can be played right now.');
      return;
    }
    _reportListen(completed: false);
    final start = tracks.isEmpty ? 0 : playable.indexOf(tracks[startIndex.clamp(0, tracks.length - 1)]);
    if (shuffle != null) _queue.shuffle = shuffle;
    _queue.replace(playable, startIndex: start < 0 ? 0 : start);
    _context = context;
    _consecutiveFailures = 0;
    _publishQueue();
    await _load(play: true);
  }

  Future<void> playNextInQueue(Track track) async {
    if (_queue.isEmpty) return playTracks([track]);
    _queue.playNext(track);
    _publishQueue();
  }

  Future<void> addToQueue(Track track) async {
    if (_queue.isEmpty) return playTracks([track]);
    _queue.addToEnd(track);
    _publishQueue();
  }

  Future<void> removeFromQueue(int playIndex) async {
    final removedCurrent = _queue.removeAt(playIndex);
    _publishQueue();
    if (_queue.isEmpty) {
      await stop();
    } else if (removedCurrent) {
      await _load(play: _engine.playing);
    }
  }

  Future<void> moveInQueue(int from, int to) async {
    _queue.move(from, to);
    _publishQueue();
  }

  /// Audio quality for every future stream. Saved on the device with the queue, so it
  /// survives restarts without any account or server-side preference.
  Future<void> setQuality(String quality) async {
    if (quality == _quality) return;
    _quality = quality;
    _streams.clear();
    _persist();
    if (_queue.current != null && !_needsLoad) {
      await _load(play: _engine.playing, position: _engine.position);
    }
  }

  // --- AudioHandler overrides (also reached from notification / lock screen / headset) --
  @override
  Future<void> play() async {
    _resumeAfterInterruption = false; // an explicit user action wins over a pending auto-resume
    if (_queue.current == null) return;
    if (_loading) {
      _playAfterLoad = true; // the in-flight load starts playback when ready
      _broadcast();
      return;
    }
    if (_errorMessage != null) {
      // Retry after a failure: fetch a fresh URL at the same spot.
      _errorMessage = null;
      await _load(play: true, position: _pendingPosition ?? _engine.position);
      return;
    }
    final cached = _streams[_queue.current!.id];
    if (_needsLoad || _engine.state == EngineState.idle || (cached != null && cached.isStale)) {
      // Never resume on an expired provider URL: re-resolve at the same position.
      await _load(play: true, position: _needsLoad ? _pendingPosition : _engine.position);
      return;
    }
    if (_engine.state == EngineState.completed) await _engine.seek(Duration.zero);
    await _engine.play();
  }

  @override
  Future<void> pause() async {
    // A manual pause must never be undone by an interruption ending later, nor by a
    // load that is still in flight.
    _resumeAfterInterruption = false;
    _playAfterLoad = false;
    await _engine.pause();
    _persist();
  }

  @override
  Future<void> setSpeed(double speed) async {
    await _engine.setSpeed(speed.clamp(0.5, 2.0));
    _broadcast();
  }

  @override
  Future<void> seek(Duration position) async {
    if (_needsLoad) {
      _pendingPosition = position;
      _broadcast();
      return;
    }
    if (_loading) {
      // Applied as soon as the new source is ready; seeking the old source would be lost.
      _seekWhileLoading = position;
      _broadcast();
      return;
    }
    await _engine.seek(position);
    _lastPosition = position;
    _broadcast();
  }

  @override
  Future<void> skipToNext() async {
    if (_queue.isEmpty) return;
    _reportListen(completed: false);
    // Repeat-one only loops on natural completion; a Next press always moves on.
    if (_queue.next()) {
      await _load(play: true);
    } else {
      // End of queue. With repeat-one the user still wants continuous playback, so
      // wrap and keep playing; otherwise go back to the first song, paused (Spotify).
      _queue.jumpTo(0);
      await _load(play: _queue.repeat == RepeatMode.one);
    }
    _publishQueue(sync: false);
  }

  @override
  Future<void> skipToPrevious() async {
    if (_queue.isEmpty) return;
    // displayPosition is the new song's position even while it is still loading (the
    // engine would still report the old song's), so a quick Next→Previous goes back and
    // repeated Previous presses walk back through the queue, like Spotify.
    switch (decidePrevious(position: displayPosition, hasPrevious: _queue.hasPrevious)) {
      case PreviousAction.restartCurrent:
        await seek(Duration.zero);
      case PreviousAction.playPrevious:
        _reportListen(completed: false);
        _queue.previous();
        await _load(play: true);
        _publishQueue(sync: false);
    }
  }

  @override
  Future<void> skipToQueueItem(int index) async {
    if (index < 0 || index >= _queue.length) return;
    _reportListen(completed: false);
    _queue.jumpTo(index);
    await _load(play: true);
    _publishQueue(sync: false);
  }

  @override
  Future<void> setShuffleMode(AudioServiceShuffleMode shuffleMode) async {
    _queue.setShuffle(shuffleMode != AudioServiceShuffleMode.none);
    _publishQueue();
  }

  @override
  Future<void> setRepeatMode(AudioServiceRepeatMode repeatMode) async {
    _queue.repeat = switch (repeatMode) {
      AudioServiceRepeatMode.none => RepeatMode.off,
      AudioServiceRepeatMode.one => RepeatMode.one,
      _ => RepeatMode.all,
    };
    _broadcast();
    _persist();
  }

  @override
  Future<void> stop() async {
    _reportListen(completed: false);
    await _engine.stop();
    _persist();
    _broadcast();
    await super.stop();
  }

  @override
  Future<void> onTaskRemoved() async {
    // App swiped away: keep playing if playing (Android), otherwise release.
    if (!_engine.playing) await stop();
  }

  // --- internals -----------------------------------------------------------------
  Future<StreamInfo> _streamFor(Track track, {bool forceRefresh = false}) async {
    // Cache is keyed by song and cleared whenever the quality setting changes.
    final cached = _streams[track.id];
    if (!forceRefresh && cached != null && !cached.isStale) return cached;
    final info = await _resolve(track.id, _quality);
    _streams[track.id] = info;
    return info;
  }

  Future<void> _load({required bool play, Duration? position}) async {
    final track = _queue.current;
    if (track == null) return;
    final generation = ++_loadGeneration;
    _errorMessage = null;
    _needsLoad = false;
    _pendingPosition = null;
    _loading = true;
    _loadPosition = position ?? Duration.zero;
    _seekWhileLoading = null;
    _playAfterLoad = play;
    _listenedSeconds = 0;
    _lastPosition = _loadPosition;
    mediaItem.add(mediaItemFor(track));
    _broadcast();
    try {
      final info = await _streamFor(track);
      if (generation != _loadGeneration) return; // user skipped meanwhile
      await _engine.setUrl(info.url, initialPosition: position);
      if (generation != _loadGeneration) return;
      final seekTo = _seekWhileLoading;
      _seekWhileLoading = null;
      if (seekTo != null) {
        await _engine.seek(seekTo);
        _lastPosition = seekTo;
        if (generation != _loadGeneration) return;
      }
      _activeStreamQuality = info.quality;
      _consecutiveFailures = 0;
      _loading = false;
      if (_playAfterLoad) await _engine.play();
      _broadcast();
      _persist();
      _prefetchNext();
    } catch (e) {
      if (generation != _loadGeneration) return;
      final failedAt = _seekWhileLoading ?? _loadPosition;
      _seekWhileLoading = null;
      _loading = false;
      await _onTrackFailed(track, e, play: _playAfterLoad, position: failedAt);
    }
  }

  void _prefetchNext() {
    final order = _queue.playOrder;
    final nextIndex = _queue.position + 1;
    if (nextIndex < order.length) {
      unawaited(_streamFor(order[nextIndex]).then((_) {}, onError: (_) {}));
    }
  }

  /// One bad song must never kill the queue: report it and move on. A lost connection
  /// is not the song's fault, so it holds the song at its position instead.
  Future<void> _onTrackFailed(Track track, Object error, {required bool play, Duration position = Duration.zero}) async {
    _streams.remove(track.id);
    final failure = AppException.from(error);
    final reason = failure.message;
    if (failure.isNetwork) {
      _errors.add('Connection lost. Press play to retry "${track.title}".');
      await _stopWithError(reason, position);
      return;
    }
    _consecutiveFailures++;
    if (_consecutiveFailures >= _queue.length || !_queue.hasNext) {
      _errors.add('Couldn\'t play "${track.title}": $reason');
      _consecutiveFailures = 0;
      await _stopWithError(reason, Duration.zero);
      return;
    }
    _errors.add('Couldn\'t play "${track.title}" — skipping. ($reason)');
    _queue.next();
    _publishQueue(sync: false);
    await _load(play: play);
  }

  /// Stop on the current song in the error state; play() retries from [position].
  Future<void> _stopWithError(String reason, Duration position) async {
    _resumeAfterInterruption = false;
    await _engine.stop();
    _needsLoad = true;
    _pendingPosition = position;
    _errorMessage = reason;
    _broadcast();
    _persist();
  }

  Future<void> _onEngineError(Object error) async {
    final track = _queue.current;
    if (track == null || _loading || _recovering) return;
    final pos = _engine.position;
    final wasPlaying = _engine.playing;
    final now = DateTime.now();
    // Failing again right after a recovery means the song is broken, not that its URL
    // expired: stop retrying it (otherwise it would loop forever).
    if (_lastRecoveredTrackId == track.id && now.difference(_lastRecoveryAt) < const Duration(seconds: 10)) {
      await _onTrackFailed(track, error, play: wasPlaying, position: pos);
      return;
    }
    // Mid-stream failure (expired token, network drop): fetch a fresh URL and continue at
    // the same position, keeping the user's play/pause state. If that fails, _load
    // reports it (network loss holds the song; a dead song is skipped).
    _recovering = true;
    _lastRecoveredTrackId = track.id;
    _lastRecoveryAt = now;
    try {
      _streams.remove(track.id);
      await _load(play: wasPlaying, position: pos);
    } finally {
      _recovering = false;
    }
  }

  Future<void> _onCompleted() async {
    if (_loading) return;
    _reportListen(completed: true);
    if (_queue.repeat == RepeatMode.one) {
      await _engine.seek(Duration.zero);
      await _engine.play();
      return;
    }
    if (_queue.next()) {
      await _load(play: true);
      _publishQueue(sync: false);
    } else {
      // Finished the queue: rewind to the first song, paused.
      await _engine.pause();
      _queue.jumpTo(0);
      await _load(play: false);
      _publishQueue(sync: false);
    }
  }

  void _onPosition(Duration pos) {
    if (_loading) return; // late events from the previous source
    final delta = pos - _lastPosition;
    if (_engine.playing && delta > Duration.zero && delta < const Duration(seconds: 2)) {
      _listenedSeconds += delta.inMilliseconds / 1000;
    }
    _lastPosition = pos;
    final track = _queue.current;
    if (track != null && _engine.playing && DateTime.now().difference(_lastProgressReport) > const Duration(seconds: 15)) {
      _lastProgressReport = DateTime.now();
      unawaited(_reporter.progress(track.id, pos.inMilliseconds / 1000, _queue.position));
      _persist();
    }
  }

  void _reportListen({required bool completed}) {
    final track = _queue.current;
    if (track == null || _listenedSeconds <= 0) return;
    final seconds = _listenedSeconds;
    _listenedSeconds = 0;
    unawaited(_reporter.complete(track.id, seconds, completed: completed, context: _context));
  }

  void _publishQueue({bool sync = true}) {
    queue.add(_queue.playOrder.map(mediaItemFor).toList());
    _queueChanges.add(null);
    _broadcast();
    _persist();
    if (sync) {
      _syncDebounce?.cancel();
      _syncDebounce = Timer(const Duration(seconds: 2), _syncSession);
    }
  }

  void _syncSession() {
    unawaited(_reporter.syncSession(
      queue: _queue.playOrder.map((t) => t.id).toList(),
      currentIndex: _queue.position,
      positionSeconds: displayPosition.inMilliseconds / 1000,
      shuffle: _queue.shuffle,
      repeatMode: _queue.repeat.name,
      quality: _quality,
      context: _context,
    ));
  }

  void _persist() {
    _persistTimer?.cancel();
    _persistTimer = Timer(const Duration(milliseconds: 500), () {
      final pos = displayPosition;
      unawaited(_store.save({
        'queue': _queue.toJson(),
        'position_ms': pos.inMilliseconds,
        'context': _context,
        'quality': _quality,
      }));
    });
  }

  Future<void> _restore() async {
    final saved = await _store.load();
    final savedQuality = saved?['quality'];
    if (savedQuality is String && AppConfig.audioQualities.containsKey(savedQuality)) _quality = savedQuality;
    if (saved == null || saved['queue'] == null) return;
    final restored = PlayQueue.fromJson(saved['queue'] as Map<String, dynamic>);
    if (restored.isEmpty) return;
    _queue
      ..replace(restored.items)
      ..order = restored.order
      ..position = restored.position
      ..shuffle = restored.shuffle
      ..repeat = restored.repeat;
    _context = saved['context'] as String?;
    // Don't touch the network on startup; resolve the stream when the user presses play.
    _needsLoad = true;
    _pendingPosition = Duration(milliseconds: (saved['position_ms'] as int?) ?? 0);
    mediaItem.add(mediaItemFor(_queue.current!));
    queue.add(_queue.playOrder.map(mediaItemFor).toList());
    _broadcast();
  }

  void _broadcast() {
    final playing = _engine.playing;
    final AudioProcessingState processing;
    if (_loading) {
      processing = AudioProcessingState.loading;
    } else if (_errorMessage != null) {
      processing = AudioProcessingState.error;
    } else if (_needsLoad) {
      processing = AudioProcessingState.ready; // paused at the restored position
    } else {
      processing = switch (_engine.state) {
        EngineState.idle => AudioProcessingState.idle,
        EngineState.loading => AudioProcessingState.loading,
        EngineState.buffering => AudioProcessingState.buffering,
        EngineState.ready => AudioProcessingState.ready,
        EngineState.completed => AudioProcessingState.completed,
      };
    }
    playbackState.add(playbackState.value.copyWith(
      controls: [
        MediaControl.skipToPrevious,
        if (playing) MediaControl.pause else MediaControl.play,
        MediaControl.skipToNext,
      ],
      systemActions: const {
        MediaAction.seek,
        MediaAction.seekForward,
        MediaAction.seekBackward,
        MediaAction.play,
        MediaAction.pause,
        MediaAction.playPause,
        MediaAction.skipToNext,
        MediaAction.skipToPrevious,
        MediaAction.stop,
      },
      androidCompactActionIndices: const [0, 1, 2],
      processingState: processing,
      playing: playing,
      updatePosition: displayPosition,
      bufferedPosition: _loading || _needsLoad ? Duration.zero : _engine.bufferedPosition,
      speed: _engine.speed,
      errorMessage: _errorMessage,
      queueIndex: _queue.isEmpty ? null : _queue.position,
      shuffleMode: _queue.shuffle ? AudioServiceShuffleMode.all : AudioServiceShuffleMode.none,
      repeatMode: switch (_queue.repeat) {
        RepeatMode.off => AudioServiceRepeatMode.none,
        RepeatMode.one => AudioServiceRepeatMode.one,
        RepeatMode.all => AudioServiceRepeatMode.all,
      },
    ));
  }

  Future<void> dispose() async {
    _persistTimer?.cancel();
    _syncDebounce?.cancel();
    await _errors.close();
    await _queueChanges.close();
    await _engine.dispose();
  }
}
