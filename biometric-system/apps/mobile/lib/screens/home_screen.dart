import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../state/auth_provider.dart';

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final user = ref.watch(authStateProvider).user;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Biometric Mobile'),
        actions: [
          IconButton(
            icon: const Icon(Icons.logout),
            onPressed: () => ref.read(authNotifierProvider).logout(),
          ),
        ],
      ),
      body: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Card(
              child: ListTile(
                leading: const Icon(Icons.person, size: 36, color: Color(0xFF6366F1)),
                title: Text(user?.email ?? user?.userId ?? '—'),
                subtitle: Text('Rôle: ${user?.role ?? "—"}'),
              ),
            ),
            const SizedBox(height: 20),
            _ActionTile(
              icon: Icons.camera_alt,
              title: 'Scanner un visage',
              subtitle: 'Reconnaissance / contrôle d\'accès',
              onTap: () => context.push('/scan'),
            ),
            _ActionTile(
              icon: Icons.assignment_ind,
              title: 'Vérification KYC',
              subtitle: 'Selfie + document d\'identité',
              onTap: () => context.push('/kyc'),
            ),
            _ActionTile(
              icon: Icons.lock,
              title: 'Activer la connexion biométrique',
              subtitle: 'Empreinte / visage du téléphone',
              onTap: () => context.push('/login/biometric'),
            ),
          ],
        ),
      ),
    );
  }
}

class _ActionTile extends StatelessWidget {
  const _ActionTile({
    required this.icon, required this.title,
    required this.subtitle, required this.onTap,
  });
  final IconData icon;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: const EdgeInsets.only(bottom: 12),
      child: ListTile(
        leading: Icon(icon, size: 30),
        title: Text(title),
        subtitle: Text(subtitle),
        trailing: const Icon(Icons.chevron_right),
        onTap: onTap,
      ),
    );
  }
}
