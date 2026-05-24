import 'dart:io';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';
import '../state/auth_provider.dart';

class KYCScreen extends ConsumerStatefulWidget {
  const KYCScreen({super.key});
  @override
  ConsumerState<KYCScreen> createState() => _KYCScreenState();
}

class _KYCScreenState extends ConsumerState<KYCScreen> {
  String _docType = 'passport';
  Map<String, dynamic>? _session;
  File? _selfie;
  File? _doc;
  bool _busy = false;
  Map<String, dynamic>? _verdict;

  Future<void> _start() async {
    setState(() => _busy = true);
    try {
      final repo = ref.read(bioRepoProvider);
      _session = await repo.startKyc(docType: _docType);
      setState(() => _verdict = null);
    } catch (e) {
      _toast('Erreur start: $e');
    } finally {
      setState(() => _busy = false);
    }
  }

  Future<void> _submit() async {
    if (_session == null || _selfie == null || _doc == null) return;
    setState(() => _busy = true);
    try {
      final repo = ref.read(bioRepoProvider);
      _verdict = await repo.submitKyc(
        sessionToken: _session!['session_token'],
        selfie: _selfie!,
        document: _doc!,
      );
      setState(() {});
    } catch (e) {
      _toast('Erreur submit: $e');
    } finally {
      setState(() => _busy = false);
    }
  }

  Future<void> _pick(bool isSelfie) async {
    final src = isSelfie ? ImageSource.camera : ImageSource.gallery;
    final picker = ImagePicker();
    final picked = await picker.pickImage(
      source: src, imageQuality: 90, maxWidth: 1600,
      preferredCameraDevice: isSelfie ? CameraDevice.front : CameraDevice.rear,
    );
    if (picked == null) return;
    setState(() {
      if (isSelfie) _selfie = File(picked.path);
      else _doc = File(picked.path);
    });
  }

  void _toast(String m) =>
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(m)));

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Vérification KYC')),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            DropdownButtonFormField<String>(
              value: _docType,
              decoration: const InputDecoration(
                labelText: 'Type de document', border: OutlineInputBorder(),
              ),
              items: const [
                DropdownMenuItem(value: 'passport',         child: Text('Passeport')),
                DropdownMenuItem(value: 'id_card',          child: Text('Carte d\'identité')),
                DropdownMenuItem(value: 'driver_license',   child: Text('Permis de conduire')),
                DropdownMenuItem(value: 'residence_permit', child: Text('Titre de séjour')),
              ],
              onChanged: (v) => setState(() => _docType = v ?? 'passport'),
            ),
            const SizedBox(height: 12),
            FilledButton(
              onPressed: _busy ? null : _start,
              child: Text(_session == null ? 'Démarrer la session' : 'Nouvelle session'),
            ),
            if (_session?['challenge'] != null) ...[
              const SizedBox(height: 12),
              Card(
                color: const Color(0xFF1E293B),
                child: Padding(
                  padding: const EdgeInsets.all(12),
                  child: Text('Challenge: ${_session!['challenge']['action']}'),
                ),
              ),
            ],
            const SizedBox(height: 16),
            _PickRow(
              label: 'Selfie', file: _selfie,
              onPick: () => _pick(true),
            ),
            _PickRow(
              label: 'Document', file: _doc,
              onPick: () => _pick(false),
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              icon: const Icon(Icons.send),
              label: Text(_busy ? 'Vérification…' : 'Soumettre'),
              onPressed: (_session == null || _selfie == null || _doc == null || _busy)
                  ? null : _submit,
            ),
            if (_verdict != null) ...[
              const SizedBox(height: 16),
              _VerdictCard(verdict: _verdict!),
            ],
          ],
        ),
      ),
    );
  }
}

class _PickRow extends StatelessWidget {
  const _PickRow({required this.label, required this.file, required this.onPick});
  final String label;
  final File? file;
  final VoidCallback onPick;
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Row(
        children: [
          if (file != null)
            ClipRRect(
              borderRadius: BorderRadius.circular(8),
              child: Image.file(file!, height: 60, width: 60, fit: BoxFit.cover),
            )
          else
            Container(
              height: 60, width: 60,
              decoration: BoxDecoration(
                color: Colors.black26, borderRadius: BorderRadius.circular(8),
              ),
              child: const Icon(Icons.image_outlined, color: Colors.white24),
            ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(label, style: const TextStyle(fontWeight: FontWeight.w500)),
          ),
          OutlinedButton(onPressed: onPick, child: const Text('Choisir')),
        ],
      ),
    );
  }
}

class _VerdictCard extends StatelessWidget {
  const _VerdictCard({required this.verdict});
  final Map<String, dynamic> verdict;
  @override
  Widget build(BuildContext context) {
    final decision = verdict['decision'] ?? '?';
    final color = decision == 'approved' ? Colors.green
               : decision == 'review'    ? Colors.amber : Colors.red;
    final flags = (verdict['fraud_flags'] as List?) ?? [];
    return Card(
      color: color.withOpacity(0.15),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(decision == 'approved' ? Icons.verified : Icons.warning, color: color),
                const SizedBox(width: 8),
                Text(decision.toString().toUpperCase(),
                  style: TextStyle(color: color, fontWeight: FontWeight.bold, fontSize: 16)),
                const Spacer(),
                Text('Confiance ${((verdict['confidence'] ?? 0) * 100).toStringAsFixed(0)}%'),
              ],
            ),
            if (verdict['face_match_score'] != null)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Text('Face match: ${((verdict['face_match_score']) * 100).toStringAsFixed(1)}%'),
              ),
            if (flags.isNotEmpty)
              Padding(
                padding: const EdgeInsets.only(top: 8),
                child: Wrap(
                  spacing: 6,
                  children: flags.map((f) => Chip(
                    label: Text(f.toString(), style: const TextStyle(fontSize: 10)),
                    visualDensity: VisualDensity.compact,
                  )).toList(),
                ),
              ),
            const SizedBox(height: 8),
            ...((verdict['reasons'] as List?) ?? [])
              .map((r) => Text('• $r', style: const TextStyle(fontSize: 12))),
          ],
        ),
      ),
    );
  }
}
