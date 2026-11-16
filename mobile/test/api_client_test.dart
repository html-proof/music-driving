import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:melodia/core/networking/api_client.dart';
import 'package:melodia/core/storage/token_storage.dart';

/// Minimal fake backend for the auth flow.
class FakeBackend implements HttpClientAdapter {
  final calls = <String>[];
  final deviceLogins = <Map<String, dynamic>>[];
  String validAccess = 'access-1';
  bool refreshRejected = false;
  int issued = 1;

  ResponseBody _json(int status, Object body) => ResponseBody.fromString(jsonEncode(body), status,
      headers: {Headers.contentTypeHeader: [Headers.jsonContentType]});

  Map<String, dynamic> _tokens() {
    issued++;
    validAccess = 'access-$issued';
    return {'access_token': validAccess, 'refresh_token': 'refresh-$issued', 'token_type': 'bearer', 'expires_in': 900};
  }

  @override
  Future<ResponseBody> fetch(RequestOptions o, Stream<Uint8List>? requestStream, Future<void>? cancelFuture) async {
    calls.add('${o.method} ${o.path}');
    switch (o.path) {
      case '/auth/device':
        deviceLogins.add(Map<String, dynamic>.from(o.data as Map));
        return _json(201, {..._tokens(), 'created': true});
      case '/auth/refresh':
        return refreshRejected ? _json(401, {'detail': 'Refresh token has expired'}) : _json(200, _tokens());
      case '/lyrics/provider-down':
        // What our backend returns while Gaana is blocking us.
        return _json(503, {'detail': 'Music provider is currently unavailable'});
      case '/gateway-hiccup':
        // A proxy/gateway error (no JSON body): genuinely transient.
        return ResponseBody.fromString('Bad Gateway', 502, headers: {Headers.contentTypeHeader: ['text/plain']});
      default:
        final auth = o.headers['Authorization'];
        if (auth != 'Bearer $validAccess') return _json(401, {'detail': 'Invalid or expired access token'});
        return _json(200, {'ok': true});
    }
  }

  @override
  void close({bool force = false}) {}
}

void main() {
  late FakeBackend backend;
  late TokenStorage tokens;
  late ApiClient api;

  setUp(() {
    FlutterSecureStorage.setMockInitialValues({});
    backend = FakeBackend();
    tokens = TokenStorage();
    final dio = Dio(BaseOptions(baseUrl: 'http://api.test'))..httpClientAdapter = backend;
    api = ApiClient(tokens: tokens, dio: dio);
  });

  test('first launch creates a device session with no user input', () async {
    await api.ensureSession();
    expect(backend.deviceLogins, hasLength(1));
    final creds = backend.deviceLogins.single;
    expect((creds['device_id'] as String).length, greaterThanOrEqualTo(16));
    expect((creds['device_secret'] as String).length, greaterThanOrEqualTo(32));
    expect((await tokens.read())!.accessToken, backend.validAccess);

    await api.ensureSession(); // already has tokens: no second call
    expect(backend.deviceLogins, hasLength(1));
  });

  test('device credentials are generated once and reused', () async {
    final a = await tokens.deviceCredentials();
    final b = await TokenStorage().deviceCredentials(); // fresh instance, same keystore
    expect(b.deviceId, a.deviceId);
    expect(b.secret, a.secret);
  });

  test('expired access token is refreshed transparently', () async {
    await api.ensureSession();
    backend.validAccess = 'rotated-away'; // server no longer accepts the stored access token
    final result = await api.get<Map<String, dynamic>>('/users/me');
    expect(result['ok'], isTrue);
    expect(backend.calls, contains('POST /auth/refresh'));
    expect(backend.deviceLogins, hasLength(1));
  });

  test('rejected refresh token silently signs the device in again', () async {
    await api.ensureSession();
    final firstCreds = backend.deviceLogins.single;
    backend.validAccess = 'rotated-away';
    backend.refreshRejected = true;
    final result = await api.get<Map<String, dynamic>>('/users/me');
    expect(result['ok'], isTrue);
    expect(backend.deviceLogins, hasLength(2));
    expect(backend.deviceLogins.last['device_id'], firstCreds['device_id']); // same account
  });

  test('a backend 503 ("provider unavailable") is not retried', () async {
    await api.ensureSession();
    backend.calls.clear();
    await expectLater(api.get<dynamic>('/lyrics/provider-down'), throwsA(anything));
    expect(backend.calls.where((c) => c == 'GET /lyrics/provider-down'), hasLength(1));
  });

  test('a gateway 502 is still retried (twice)', () async {
    await api.ensureSession();
    backend.calls.clear();
    await expectLater(api.get<dynamic>('/gateway-hiccup'), throwsA(anything));
    expect(backend.calls.where((c) => c == 'GET /gateway-hiccup'), hasLength(3));
  });
}
