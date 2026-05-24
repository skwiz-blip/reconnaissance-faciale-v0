import 'api_client.dart';
import 'token_storage.dart';

class AuthUser {
  AuthUser({required this.userId, required this.role, this.email});
  final String userId;
  final String role;
  final String? email;
}

class AuthRepository {
  AuthRepository(this._api);
  final ApiClient _api;

  Future<AuthUser> login(String email, String password) async {
    final r = await _api.dio.post('/api/v1/auth/login', data: {
      'email': email, 'password': password,
    });
    final d = r.data as Map<String, dynamic>;
    await TokenStorage.instance.save(
      access: d['access_token'], refresh: d['refresh_token'],
      userId: d['user_id'], role: d['role'],
    );
    final me = await _api.dio.get('/api/v1/auth/me');
    return AuthUser(
      userId: me.data['user_id'], role: me.data['role'], email: me.data['email'],
    );
  }

  Future<void> logout() async {
    try { await _api.dio.post('/api/v1/auth/logout'); } catch (_) {}
    await TokenStorage.instance.clear();
  }

  Future<AuthUser?> currentUser() async {
    final token = await TokenStorage.instance.getAccess();
    if (token == null) return null;
    try {
      final me = await _api.dio.get('/api/v1/auth/me');
      return AuthUser(
        userId: me.data['user_id'], role: me.data['role'], email: me.data['email'],
      );
    } catch (_) {
      await TokenStorage.instance.clear();
      return null;
    }
  }
}
