import 'package:flutter/foundation.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/api_client.dart';
import '../api/auth_repository.dart';
import '../api/biometric_repository.dart';

class AuthState {
  AuthState({this.user, this.loading = false, this.error});
  final AuthUser? user;
  final bool loading;
  final String? error;

  AuthState copy({AuthUser? user, bool? loading, String? error, bool clearUser = false}) =>
      AuthState(
        user: clearUser ? null : (user ?? this.user),
        loading: loading ?? this.loading,
        error: error,
      );
}

final apiClientProvider = Provider<ApiClient>((_) => ApiClient());
final authRepoProvider  = Provider<AuthRepository>((ref) => AuthRepository(ref.watch(apiClientProvider)));
final bioRepoProvider   = Provider<BiometricRepository>((ref) => BiometricRepository(ref.watch(apiClientProvider)));

class AuthNotifier extends ChangeNotifier {
  AuthNotifier(this._repo) {
    _bootstrap();
  }
  final AuthRepository _repo;
  AuthState _state = AuthState(loading: true);
  AuthState get state => _state;

  Future<void> _bootstrap() async {
    final me = await _repo.currentUser();
    _state = AuthState(user: me);
    notifyListeners();
  }

  Future<void> login(String email, String password) async {
    _state = _state.copy(loading: true, error: null);
    notifyListeners();
    try {
      final u = await _repo.login(email, password);
      _state = AuthState(user: u);
    } catch (e) {
      _state = AuthState(error: e.toString());
    }
    notifyListeners();
  }

  Future<void> logout() async {
    await _repo.logout();
    _state = AuthState();
    notifyListeners();
  }
}

final authNotifierProvider = ChangeNotifierProvider<AuthNotifier>(
  (ref) => AuthNotifier(ref.watch(authRepoProvider)),
);
final authStateProvider = Provider<AuthState>(
  (ref) => ref.watch(authNotifierProvider).state,
);
