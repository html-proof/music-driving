import 'dart:ui' show Color;

import 'package:audio_service/audio_service.dart';

// A single MediaSession + foreground service: the native media notification,
// lock screen, Now Playing (iOS) and media buttons are all derived from it,
// so there is never a second (duplicate) notification.
const melodiaAudioServiceConfig = AudioServiceConfig(
  androidNotificationChannelId: 'com.melodia.app.playback',
  androidNotificationChannelName: 'Playback',
  androidNotificationChannelDescription: 'Media controls for the song that is playing',
  androidNotificationIcon: 'drawable/ic_stat_music',
  // Ongoing while playing; when paused the service leaves the foreground so the
  // user can swipe the notification away (which stops playback).
  androidNotificationOngoing: true,
  androidStopForegroundOnPause: true,
  // Some OEM skins only draw the notification seek bar with a solid colour.
  notificationColor: Color(0xFF121212),
  // audio_service publishes the new title/artist immediately and the new cover
  // once downloaded (stale downloads are dropped), so a cover never belongs to
  // the previous song. Downscale to keep the MediaSession bitmap small.
  artDownscaleWidth: 512,
  artDownscaleHeight: 512,
);
