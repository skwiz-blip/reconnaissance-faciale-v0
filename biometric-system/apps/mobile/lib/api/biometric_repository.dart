import 'dart:convert';
import 'dart:io';
import 'api_client.dart';

class BiometricRepository {
  BiometricRepository(this._api);
  final ApiClient _api;

  Future<Map<String, dynamic>> recognizeFromFile(File file, {bool checkLiveness = true}) async {
    final bytes = await file.readAsBytes();
    final base64Img = base64Encode(bytes);
    final r = await _api.dio.post('/api/v1/recognize', data: {
      'image_base64': 'data:image/jpeg;base64,$base64Img',
      'check_liveness': checkLiveness,
    });
    return Map<String, dynamic>.from(r.data);
  }

  Future<Map<String, dynamic>> startKyc({required String docType}) async {
    final r = await _api.dio.post('/api/v1/kyc/sessions', data: {
      'doc_type': docType, 'issue_challenge': true,
    });
    return Map<String, dynamic>.from(r.data);
  }

  Future<Map<String, dynamic>> submitKyc({
    required String sessionToken,
    required File selfie,
    required File document,
  }) async {
    final selfieB64   = base64Encode(await selfie.readAsBytes());
    final documentB64 = base64Encode(await document.readAsBytes());
    final r = await _api.dio.post('/api/v1/kyc/sessions/submit', data: {
      'session_token': sessionToken,
      'selfie_base64': 'data:image/jpeg;base64,$selfieB64',
      'document_base64': 'data:image/jpeg;base64,$documentB64',
    });
    return Map<String, dynamic>.from(r.data);
  }
}
