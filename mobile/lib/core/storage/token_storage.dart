import 'dart:convert';
import 'dart:math';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class TokenPair {
  const TokenPair(this.accessToken, this.refreshToken);
  final String accessToken;
  final String refreshToken;
}

class DeviceCredentials {
  const DeviceCredentials(this.deviceId, this.secret);
  final String deviceId;
  final String secret;
}

/// Session tokens and this install's device credentials, kept in the platform
/// keystore/keychain (never in plain preferences).
class TokenStorage {
  TokenStorage([FlutterSecureStorage? storage]) : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;
  static const _access = 'access_token';
  static const _refresh = 'refresh_token';
  static const _deviceId = 'device_id';
  static const _deviceSecret = 'device_secret';

  TokenPair? _cached;
  DeviceCredentials? _device;

  Future<TokenPair?> read() async {
    if (_cached != null) return _cached;
    final a = await _storage.read(key: _access);
    final r = await _storage.read(key: _refresh);
    if (a == null || r == null) return null;
    return _cached = TokenPair(a, r);
  }

  Future<void> save(TokenPair tokens) async {
    _cached = tokens;
    await _storage.write(key: _access, value: tokens.accessToken);
    await _storage.write(key: _refresh, value: tokens.refreshToken);
  }

  Future<void> clear() async {
    _cached = null;
    await _storage.delete(key: _access);
    await _storage.delete(key: _refresh);
  }

  /// This install's anonymous identity; generated once (cryptographically random).
  Future<DeviceCredentials> deviceCredentials() async {
    if (_device != null) return _device!;
    var id = await _storage.read(key: _deviceId);
    var secret = await _storage.read(key: _deviceSecret);
    if (id == null || secret == null) {
      id = _random(24);
      secret = _random(48); // 384 bits
      await _storage.write(key: _deviceId, value: id);
      await _storage.write(key: _deviceSecret, value: secret);
    }
    return _device = DeviceCredentials(id, secret);
  }

  static String _random(int bytes) {
    final rnd = Random.secure();
    return base64Url.encode(List<int>.generate(bytes, (_) => rnd.nextInt(256))).replaceAll('=', '');
  }
}
