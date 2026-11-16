import 'package:flutter/foundation.dart' show kIsWeb;

/// Build-time configuration. Override with
/// `flutter run --dart-define=API_BASE_URL=https://api.example.com/api/v1`.
class AppConfig {
  static const _apiBaseUrlOverride = String.fromEnvironment('API_BASE_URL');

  /// Without an override: Chrome reaches a local backend at localhost; Android emulators reach the
  /// host machine at 10.0.2.2.
  static String get apiBaseUrl => _apiBaseUrlOverride.isNotEmpty
      ? _apiBaseUrlOverride
      : (kIsWeb ? 'http://localhost:8000/api/v1' : 'http://10.0.2.2:8000/api/v1');

  static const appName = 'Melodia';
  static const connectTimeout = Duration(seconds: 10);
  static const receiveTimeout = Duration(seconds: 30);
  static const searchDebounce = Duration(milliseconds: 350);

  /// Spotify-style "previous" threshold.
  static const restartThreshold = Duration(seconds: 3);

  static const audioQualities = {
    'low': 'Low (16 kbps)',
    'medium': 'Medium (64 kbps)',
    'high': 'High (128 kbps)',
    'very_high': 'Very high (320 kbps)',
  };

  static const supportedLanguages = [
    'English', 'Hindi', 'Punjabi', 'Tamil', 'Telugu', 'Bengali', 'Marathi', 'Kannada', 'Malayalam', 'Gujarati',
  ];
}
