import 'package:dio/dio.dart';

/// User-presentable error. Never replace these with a generic success message.
class AppException implements Exception {
  const AppException(this.message, {this.statusCode, this.isNetwork = false});

  final String message;
  final int? statusCode;
  final bool isNetwork;

  bool get isNotFound => statusCode == 404;
  bool get isUnauthorized => statusCode == 401;

  factory AppException.from(Object error) {
    if (error is AppException) return error;
    if (error is DioException) {
      final inner = error.error;
      if (inner is AppException) return inner;
      switch (error.type) {
        case DioExceptionType.connectionTimeout:
        case DioExceptionType.sendTimeout:
        case DioExceptionType.receiveTimeout:
        case DioExceptionType.connectionError:
          return const AppException('Can\'t reach the server. Check your connection.', isNetwork: true);
        case DioExceptionType.cancel:
          return const AppException('Request cancelled');
        default:
          break;
      }
      final code = error.response?.statusCode;
      final data = error.response?.data;
      String? detail;
      if (data is Map && data['detail'] != null) {
        final d = data['detail'];
        detail = d is String ? d : (d is List && d.isNotEmpty ? (d.first['msg']?.toString()) : d.toString());
      }
      return AppException(detail ?? _defaultFor(code), statusCode: code);
    }
    return AppException(error.toString());
  }

  static String _defaultFor(int? code) => switch (code) {
        401 => 'Please sign in again.',
        403 => 'You don\'t have access to this.',
        404 => 'Not found.',
        429 => 'Too many requests. Please wait a moment.',
        503 => 'The music provider is unavailable right now.',
        _ => 'Something went wrong (${code ?? 'unknown'}).',
      };

  @override
  String toString() => message;
}
