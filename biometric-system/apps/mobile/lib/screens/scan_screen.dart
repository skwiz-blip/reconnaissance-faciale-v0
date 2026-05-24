import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import '../state/auth_provider.dart';

class ScanScreen extends ConsumerStatefulWidget {
  const ScanScreen({super.key});
  @override
  ConsumerState<ScanScreen> createState() => _ScanScreenState();
}

class _ScanScreenState extends ConsumerState<ScanScreen> {
  File? _file;
  bool _busy = false;
  Map<String, dynamic>? _result;

  Future<void> _pick(ImageSource src) async {
    final picker = ImagePicker();
    final picked = await picker.pickImage(source: src, imageQuality: 85,
                                          maxWidth: 1280, preferredCameraDevice: CameraDevice.front);
    if (picked == null) return;
    setState(() { _file = File(picked.path); _result = null; });
  }

  Future<void> _send() async {
    if (_file == null) return;
    setState(() => _busy = true);
    try {
      final repo = ref.read(bioRepoProvider);
      _result = await repo.recognizeFromFile(_file!, checkLiveness: true);
      setState(() {});
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('Erreur: $e')));
    } finally {
      setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Scan visage')),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            if (_file != null)
              ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: Image.file(_file!, height: 240, fit: BoxFit.cover),
              )
            else
              Container(
                height: 240,
                decoration: BoxDecoration(
                  color: Colors.black26,
                  borderRadius: BorderRadius.circular(12),
                ),
                child: const Center(
                  child: Icon(Icons.face_outlined, size: 64, color: Colors.white24),
                ),
              ),
            const SizedBox(height: 16),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    icon: const Icon(Icons.photo_camera),
                    label: const Text('Caméra'),
                    onPressed: () => _pick(ImageSource.camera),
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: OutlinedButton.icon(
                    icon: const Icon(Icons.photo_library),
                    label: const Text('Galerie'),
                    onPressed: () => _pick(ImageSource.gallery),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 8),
            FilledButton.icon(
              icon: const Icon(Icons.search),
              label: Text(_busy ? 'Analyse…' : 'Reconnaître'),
              onPressed: (_file == null || _busy) ? null : _send,
            ),
            const SizedBox(height: 16),
            if (_result != null) _ResultCard(result: _result!),
          ],
        ),
      ),
    );
  }
}

class _ResultCard extends StatelessWidget {
  const _ResultCard({required this.result});
  final Map<String, dynamic> result;

  @override
  Widget build(BuildContext context) {
    final matches = (result['matches'] as List?) ?? [];
    final isLive = result['is_live'] == true;
    final ev = result['event_type'] ?? '?';
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(
                  ev == 'recognized' ? Icons.check_circle :
                  ev == 'unknown'    ? Icons.help_outline :
                  Icons.warning_amber,
                  color:
                    ev == 'recognized' ? Colors.greenAccent :
                    ev == 'unknown'    ? Colors.amberAccent :
                    Colors.redAccent,
                ),
                const SizedBox(width: 8),
                Text(ev.toString().toUpperCase(),
                     style: const TextStyle(fontWeight: FontWeight.bold)),
                const Spacer(),
                Text('${(result['processing_ms'] ?? 0).toStringAsFixed(0)} ms',
                     style: const TextStyle(color: Colors.white54, fontSize: 12)),
              ],
            ),
            const SizedBox(height: 8),
            Text('Liveness: ${isLive ? "OK" : "KO"} '
                 '(${((result['liveness_score'] ?? 0) * 100).toStringAsFixed(0)}%)'),
            const SizedBox(height: 12),
            if (matches.isNotEmpty)
              ...matches.map((m) {
                final sim = (m['similarity'] ?? 0).toDouble();
                return ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const Icon(Icons.person),
                  title: Text(m['full_name'] ?? '—'),
                  subtitle: Text('rôle: ${m['role']} · sim ${(sim * 100).toStringAsFixed(1)}%'),
                );
              })
            else
              const Text('Aucun match', style: TextStyle(color: Colors.white54)),
          ],
        ),
      ),
    );
  }
}
