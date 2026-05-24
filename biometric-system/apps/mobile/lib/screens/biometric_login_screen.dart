import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:local_auth/local_auth.dart';

class BiometricLoginScreen extends StatelessWidget {
  const BiometricLoginScreen({super.key});

  Future<void> _authenticate(BuildContext context) async {
    final auth = LocalAuthentication();
    try {
      final canDo = await auth.canCheckBiometrics;
      if (!canDo) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Biométrie indisponible sur cet appareil')),
        );
        return;
      }
      final ok = await auth.authenticate(
        localizedReason: 'Authentifiez-vous pour ouvrir l\'application',
        options: const AuthenticationOptions(
          biometricOnly: true, stickyAuth: true,
        ),
      );
      if (ok && context.mounted) {
        // TODO: vérifier qu'on a un refresh_token valide stocké, sinon retour login
        context.go('/');
      }
    } catch (e) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Erreur: $e')),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Connexion biométrique')),
      body: Center(
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            const Icon(Icons.face_retouching_natural, size: 96, color: Color(0xFF6366F1)),
            const SizedBox(height: 24),
            const Text('Touchez le capteur ou regardez la caméra'),
            const SizedBox(height: 24),
            FilledButton.icon(
              icon: const Icon(Icons.fingerprint),
              label: const Text('Authentifier'),
              onPressed: () => _authenticate(context),
            ),
            TextButton(
              onPressed: () => context.go('/login'),
              child: const Text('Utiliser email + mot de passe'),
            ),
          ],
        ),
      ),
    );
  }
}
