import 'dart:async';

import 'package:audio_service/audio_service.dart';
import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'core/config/app_config.dart';
import 'core/networking/api_client.dart';
import 'core/storage/local_cache.dart';
import 'core/storage/token_storage.dart';
import 'core/theme/app_theme.dart';
import 'features/player/audio_engine.dart';
import 'features/player/audio_handler.dart';
import 'features/player/audio_service_config.dart';
import 'providers/core_providers.dart';
import 'routing/app_router.dart';
import 'services/music_repository.dart';
import 'services/playback_repository.dart';

final scaffoldMessengerKey = GlobalKey<ScaffoldMessengerState>();

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  final prefs = await SharedPreferences.getInstance();
  final tokens = TokenStorage();
  // The device id doubles as the installation id the backend uses for this device.
  final installationId = (await tokens.deviceCredentials()).deviceId;
  final LocalCache cache = kIsWeb ? PrefsLocalCache(prefs) : SqliteLocalCache();
  final api = ApiClient(tokens: tokens);
  final music = MusicRepository(api, cache);
  final playbackRepo = PlaybackRepository(api, tokens, installationId);

  // One audio handler for the whole app: UI, notification, lock screen and
  // Bluetooth/headset buttons all control this instance.
  final handler = await AudioService.init(
    builder: () => MelodiaAudioHandler(
      engine: JustAudioEngine(),
      resolveStream: music.stream,
      reporter: playbackRepo,
      store: PrefsQueueStore(prefs),
    ),
    config: melodiaAudioServiceConfig,
  );
  await handler.init();

  final scope = ProviderContainer(overrides: [
    sharedPrefsProvider.overrideWithValue(prefs),
    tokenStorageProvider.overrideWithValue(tokens),
    localCacheProvider.overrideWithValue(cache),
    apiClientProvider.overrideWithValue(api),
    audioHandlerProvider.overrideWithValue(handler),
    playbackRepositoryProvider.overrideWithValue(playbackRepo),
    installationIdProvider.overrideWithValue(installationId),
  ]);

  runApp(UncontrolledProviderScope(container: scope, child: const MelodiaApp()));
}

class MelodiaApp extends ConsumerStatefulWidget {
  const MelodiaApp({super.key});
  @override
  ConsumerState<MelodiaApp> createState() => _MelodiaAppState();
}

class _MelodiaAppState extends ConsumerState<MelodiaApp> {
  StreamSubscription<String>? _errors;

  @override
  void initState() {
    super.initState();
    // Surface playback problems (skipped songs, provider outages) wherever the user is.
    _errors = ref.read(audioHandlerProvider).errors.listen((msg) {
      scaffoldMessengerKey.currentState
        ?..hideCurrentSnackBar()
        ..showSnackBar(SnackBar(content: Text(msg)));
    });
  }

  @override
  void dispose() {
    _errors?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      title: AppConfig.appName,
      debugShowCheckedModeBanner: false,
      theme: buildDarkTheme(),
      darkTheme: buildDarkTheme(),
      themeMode: ThemeMode.dark,
      scaffoldMessengerKey: scaffoldMessengerKey,
      routerConfig: ref.watch(routerProvider),
    );
  }
}
