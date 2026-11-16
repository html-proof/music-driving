import '../core/networking/api_client.dart';
import '../core/storage/token_storage.dart';
import '../features/player/audio_handler.dart';

/// Reports playback to the backend (listening history + cross-device session).
/// Failures are swallowed here on purpose: reporting must never interrupt playback.
class PlaybackRepository implements PlaybackReporter {
  PlaybackRepository(this.api, this.tokens, this.installationId);

  final ApiClient api;
  final TokenStorage tokens;
  final String installationId;
  String? _sessionId;

  Future<bool> get _signedIn async => await tokens.read() != null;

  @override
  Future<void> syncSession({
    required List<String> queue,
    required int currentIndex,
    required double positionSeconds,
    required bool shuffle,
    required String repeatMode,
    required String quality,
    String? context,
  }) async {
    if (!await _signedIn || queue.isEmpty) return;
    try {
      final j = await api.post<Map<String, dynamic>>('/playback/session', data: {
        'queue': queue.take(500).toList(),
        'current_index': currentIndex.clamp(0, queue.length - 1),
        'position_seconds': positionSeconds,
        'shuffle': shuffle,
        'repeat_mode': repeatMode,
        'quality': quality,
        'context': context,
        'installation_id': installationId,
      });
      _sessionId = j['id'] as String?;
    } catch (_) {}
  }

  @override
  Future<void> progress(String songId, double positionSeconds, int index) async {
    if (!await _signedIn || _sessionId == null) return;
    try {
      await api.post('/playback/progress', data: {
        'session_id': _sessionId,
        'song_id': songId,
        'position_seconds': positionSeconds,
        'current_index': index,
      });
    } catch (_) {}
  }

  @override
  Future<void> complete(String songId, double secondsListened, {required bool completed, String? context}) async {
    if (!await _signedIn) return;
    try {
      await api.post('/playback/complete', data: {
        'session_id': _sessionId,
        'song_id': songId,
        'seconds_listened': secondsListened,
        'completed': completed,
        'context': context,
      });
    } catch (_) {}
  }
}
