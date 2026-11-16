import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/errors/app_exception.dart';
import '../../models/user.dart';
import '../../providers/core_providers.dart';

enum SessionStatus { starting, ready, failed }

class SessionState {
  const SessionState(this.status, {this.user, this.offline = false, this.error});
  final SessionStatus status;
  final AppUser? user;
  final bool offline; // running from the cached profile because the server is unreachable
  final String? error;
}

/// Starts (or creates, on first launch) this device's anonymous account. No login UI.
class SessionController extends Notifier<SessionState> {
  @override
  SessionState build() {
    Future.microtask(start);
    return const SessionState(SessionStatus.starting);
  }

  Future<void> start() async {
    state = const SessionState(SessionStatus.starting);
    final repo = ref.read(accountRepositoryProvider);
    try {
      await repo.ensureSession();
      final user = await repo.me();
      state = SessionState(SessionStatus.ready, user: user);
      await ref.read(audioHandlerProvider).setQuality(user.preferences.audioQuality);
    } on AppException catch (e) {
      final cached = await repo.cachedMe();
      state = cached != null
          ? SessionState(SessionStatus.ready, user: cached, offline: true)
          : SessionState(SessionStatus.failed, error: e.message);
    }
  }

  Future<void> updatePreferences({List<String>? languages, String? audioQuality, bool? allowExplicit}) async {
    final user = state.user;
    if (user == null) return;
    final prefs = await ref.read(accountRepositoryProvider).updatePreferences({
      'languages': ?languages,
      'audio_quality': ?audioQuality,
      'allow_explicit': ?allowExplicit,
    });
    state = SessionState(SessionStatus.ready, user: user.copyWith(preferences: prefs));
    if (audioQuality != null) await ref.read(audioHandlerProvider).setQuality(audioQuality);
  }

  Future<void> updateName(String name) async {
    final updated = await ref.read(accountRepositoryProvider).updateProfile(displayName: name.trim());
    state = SessionState(SessionStatus.ready, user: updated);
  }

  /// Erase everything (playlists, likes, history) and continue with a fresh account.
  Future<void> deleteMyData() async {
    await ref.read(audioHandlerProvider).stop();
    await ref.read(accountRepositoryProvider).deleteMyData();
    await start();
  }
}

final sessionProvider = NotifierProvider<SessionController, SessionState>(SessionController.new);
