import 'dart:async';
import 'dart:io' show Platform;

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

import '../config/app_config.dart';
import '../errors/app_exception.dart';
import '../storage/token_storage.dart';

/// Dio wrapper: bearer auth with silent device sign-in, single-flight refresh-token
/// rotation, and retries for idempotent requests on transient failures.
///
/// There is no login: each install has random device credentials, and the client
/// exchanges them for tokens whenever it has none or its refresh token is rejected.
class ApiClient {
  ApiClient({required this.tokens, String? baseUrl, Dio? dio})
      : dio = dio ??
            Dio(BaseOptions(
              baseUrl: baseUrl ?? AppConfig.apiBaseUrl,
              connectTimeout: AppConfig.connectTimeout,
              receiveTimeout: AppConfig.receiveTimeout,
              contentType: 'application/json',
            )) {
    this.dio.interceptors.add(InterceptorsWrapper(onRequest: _onRequest, onError: _onError));
  }

  final Dio dio;
  final TokenStorage tokens;
  Future<bool>? _renewing;

  static const _retryKey = 'retry_count';
  static const _authRetried = 'auth_retried';

  static String get _platform =>
      kIsWeb ? 'web' : (Platform.isAndroid ? 'android' : (Platform.isIOS ? 'ios' : 'other'));

  /// Make sure this device has tokens (creating its account on first launch).
  /// Throws [AppException] when the server can't be reached.
  Future<void> ensureSession() async {
    if (await tokens.read() != null) return;
    await _deviceSignIn();
  }

  Future<void> _deviceSignIn() async {
    final creds = await tokens.deviceCredentials();
    try {
      final resp = await dio.post('/auth/device',
          data: {'device_id': creds.deviceId, 'device_secret': creds.secret, 'platform': _platform},
          options: Options(headers: {'Authorization': null}, extra: {_authRetried: true}));
      await tokens.save(TokenPair(resp.data['access_token'] as String, resp.data['refresh_token'] as String));
    } catch (e) {
      throw AppException.from(e);
    }
  }

  Future<void> _onRequest(RequestOptions options, RequestInterceptorHandler handler) async {
    final isAuthCall = options.path.startsWith('/auth/');
    if (!isAuthCall) {
      final t = await tokens.read();
      if (t != null && options.headers['Authorization'] == null) {
        options.headers['Authorization'] = 'Bearer ${t.accessToken}';
      }
    }
    handler.next(options);
  }

  Future<void> _onError(DioException err, ErrorInterceptorHandler handler) async {
    final req = err.requestOptions;
    final isAuthCall = req.path.startsWith('/auth/');

    // 401 -> rotate the refresh token (or sign the device in again), then replay once.
    if (err.response?.statusCode == 401 && !isAuthCall && req.extra[_authRetried] != true) {
      if (await _renew()) {
        final t = await tokens.read();
        req.headers['Authorization'] = 'Bearer ${t!.accessToken}';
        req.extra[_authRetried] = true;
        try {
          return handler.resolve(await dio.fetch(req));
        } on DioException catch (e) {
          return handler.next(e);
        }
      }
    }

    // Retry GETs on network errors / 502-504 with exponential backoff.
    final retries = (req.extra[_retryKey] as int?) ?? 0;
    final code = err.response?.statusCode;
    final transient = err.type == DioExceptionType.connectionError ||
        err.type == DioExceptionType.connectionTimeout ||
        err.type == DioExceptionType.receiveTimeout ||
        (code != null && code >= 502 && code <= 504);
    if (req.method == 'GET' && transient && retries < 2 && !(req.cancelToken?.isCancelled ?? false)) {
      req.extra[_retryKey] = retries + 1;
      await Future.delayed(Duration(milliseconds: 400 * (1 << retries)));
      try {
        return handler.resolve(await dio.fetch(req));
      } on DioException catch (e) {
        return handler.next(e);
      }
    }
    handler.next(err);
  }

  /// Single-flight: concurrent 401s share one renewal.
  Future<bool> _renew() {
    return _renewing ??= () async {
      try {
        final t = await tokens.read();
        if (t != null) {
          try {
            final resp = await dio.post('/auth/refresh', data: {'refresh_token': t.refreshToken},
                options: Options(headers: {'Authorization': null}));
            await tokens.save(TokenPair(resp.data['access_token'] as String, resp.data['refresh_token'] as String));
            return true;
          } on DioException catch (e) {
            if (e.response?.statusCode != 401) return false; // offline etc.: keep the tokens
            await tokens.clear();
          }
        }
        // Refresh token missing, expired or revoked: sign the device in again.
        await _deviceSignIn();
        return true;
      } catch (_) {
        return false;
      } finally {
        Future.microtask(() => _renewing = null);
      }
    }();
  }

  Future<T> get<T>(String path, {Map<String, dynamic>? query, CancelToken? cancelToken}) =>
      _wrap(() => dio.get(path, queryParameters: query, cancelToken: cancelToken));

  Future<T> post<T>(String path, {Object? data, Map<String, dynamic>? query}) =>
      _wrap(() => dio.post(path, data: data, queryParameters: query));

  Future<T> put<T>(String path, {Object? data}) => _wrap(() => dio.put(path, data: data));

  Future<T> patch<T>(String path, {Object? data}) => _wrap(() => dio.patch(path, data: data));

  Future<T> delete<T>(String path, {Object? data, Map<String, dynamic>? query}) =>
      _wrap(() => dio.delete(path, data: data, queryParameters: query));

  Future<T> _wrap<T>(Future<Response> Function() call) async {
    try {
      final resp = await call();
      return resp.data as T;
    } catch (e) {
      throw AppException.from(e);
    }
  }
}
