import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../core/networking/api_client.dart';
import '../core/storage/local_cache.dart';
import '../core/storage/token_storage.dart';
import '../features/player/audio_handler.dart';
import '../services/account_repository.dart';
import '../services/library_repository.dart';
import '../services/music_repository.dart';
import '../services/playback_repository.dart';

/// Overridden in main() with the real instances (created before runApp).
final sharedPrefsProvider = Provider<SharedPreferences>((ref) => throw UnimplementedError('override in main'));
final tokenStorageProvider = Provider<TokenStorage>((ref) => throw UnimplementedError('override in main'));
final localCacheProvider = Provider<LocalCache>((ref) => throw UnimplementedError('override in main'));
final apiClientProvider = Provider<ApiClient>((ref) => throw UnimplementedError('override in main'));
final audioHandlerProvider = Provider<MelodiaAudioHandler>((ref) => throw UnimplementedError('override in main'));
final playbackRepositoryProvider = Provider<PlaybackRepository>((ref) => throw UnimplementedError('override in main'));
final installationIdProvider = Provider<String>((ref) => throw UnimplementedError('override in main'));

final musicRepositoryProvider =
    Provider<MusicRepository>((ref) => MusicRepository(ref.watch(apiClientProvider), ref.watch(localCacheProvider)));
final libraryRepositoryProvider =
    Provider<LibraryRepository>((ref) => LibraryRepository(ref.watch(apiClientProvider), ref.watch(localCacheProvider)));
final accountRepositoryProvider = Provider<AccountRepository>((ref) =>
    AccountRepository(ref.watch(apiClientProvider), ref.watch(tokenStorageProvider), ref.watch(localCacheProvider)));
