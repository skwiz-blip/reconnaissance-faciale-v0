import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class TokenStorage {
  TokenStorage._();
  static final instance = TokenStorage._();
  final _store = const FlutterSecureStorage();

  static const _kAccess  = 'bio_access';
  static const _kRefresh = 'bio_refresh';
  static const _kUserId  = 'bio_user_id';
  static const _kRole    = 'bio_role';

  Future<void> save({
    required String access,
    required String refresh,
    required String userId,
    required String role,
  }) async {
    await Future.wait([
      _store.write(key: _kAccess,  value: access),
      _store.write(key: _kRefresh, value: refresh),
      _store.write(key: _kUserId,  value: userId),
      _store.write(key: _kRole,    value: role),
    ]);
  }

  Future<String?> getAccess()  => _store.read(key: _kAccess);
  Future<String?> getRefresh() => _store.read(key: _kRefresh);
  Future<String?> getUserId()  => _store.read(key: _kUserId);
  Future<String?> getRole()    => _store.read(key: _kRole);

  Future<void> clear() async {
    await Future.wait([
      _store.delete(key: _kAccess),
      _store.delete(key: _kRefresh),
      _store.delete(key: _kUserId),
      _store.delete(key: _kRole),
    ]);
  }
}
