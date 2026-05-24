import 'package:dio/dio.dart';
import 'token_storage.dart';

class ApiClient {
  ApiClient({String? baseUrl})
      : _dio = Dio(BaseOptions(
          baseUrl: baseUrl ?? const String.fromEnvironment(
            'API_URL', defaultValue: 'http://10.0.2.2:8000',
          ),
          connectTimeout: const Duration(seconds: 10),
          receiveTimeout: const Duration(seconds: 30),
        )) {
    _dio.interceptors.add(InterceptorsWrapper(
      onRequest: (options, handler) async {
        final token = await TokenStorage.instance.getAccess();
        if (token != null) {
          options.headers['Authorization'] = 'Bearer $token';
        }
        handler.next(options);
      },
      onError: (err, handler) async {
        // Tente refresh sur 401 (sauf sur /auth/*)
        if (err.response?.statusCode == 401 &&
            !(err.requestOptions.path.contains('/auth/'))) {
          final refresh = await TokenStorage.instance.getRefresh();
          if (refresh != null) {
            try {
              final r = await _dio.post(
                '/api/v1/auth/refresh',
                data: {'refresh_token': refresh},
                options: Options(headers: {'Content-Type': 'application/json'}),
              );
              final data = r.data as Map<String, dynamic>;
              await TokenStorage.instance.save(
                access:  data['access_token'],
                refresh: data['refresh_token'],
                userId:  data['user_id'],
                role:    data['role'],
              );
              // Re-fait la requête originale avec le nouveau token
              final retried = await _dio.fetch(err.requestOptions
                ..headers['Authorization'] = 'Bearer ${data['access_token']}');
              return handler.resolve(retried);
            } catch (_) {
              await TokenStorage.instance.clear();
            }
          }
        }
        handler.next(err);
      },
    ));
  }

  final Dio _dio;
  Dio get dio => _dio;
}
