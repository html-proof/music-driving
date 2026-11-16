import '../core/networking/api_client.dart';
import '../core/storage/local_cache.dart';
import '../core/storage/token_storage.dart';
import '../models/user.dart';

/// The device's anonymous account (no login): profile, preferences and data reset.
class AccountRepository {
  AccountRepository(this.api, this.tokens, this.cache);

  final ApiClient api;
  final TokenStorage tokens;
  final LocalCache cache;

  Future<void> ensureSession() => api.ensureSession();

  Future<AppUser> me() async {
    final j = await api.get<Map<String, dynamic>>('/users/me');
    await cache.write('me', j);
    return AppUser.fromJson(j);
  }

  Future<AppUser?> cachedMe() async {
    final c = await cache.read('me');
    return c == null ? null : AppUser.fromJson(c['data'] as Map<String, dynamic>);
  }

  Future<UserPreferences> updatePreferences(Map<String, dynamic> changes) async =>
      UserPreferences.fromJson(await api.patch('/users/me/preferences', data: changes));

  Future<AppUser> updateProfile({required String displayName}) async =>
      AppUser.fromJson(await api.patch('/users/me', data: {'display_name': displayName}));

  /// Permanently deletes this device's account and everything in it, then starts a
  /// fresh, empty account for the same device.
  Future<void> deleteMyData() async {
    await api.delete('/users/me');
    await tokens.clear();
    await cache.clear();
    await api.ensureSession();
  }
}
