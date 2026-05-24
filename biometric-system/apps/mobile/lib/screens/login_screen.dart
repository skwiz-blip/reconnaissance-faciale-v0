import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import '../state/auth_provider.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});
  @override
  ConsumerState<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends ConsumerState<LoginScreen> {
  final _email = TextEditingController();
  final _password = TextEditingController();
  bool _hidePassword = true;

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authNotifierProvider);
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(24),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              const Icon(Icons.fingerprint, size: 72, color: Color(0xFF6366F1)),
              const SizedBox(height: 16),
              const Text('Biometric Mobile',
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.bold)),
              const SizedBox(height: 32),
              TextField(
                controller: _email,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(
                  labelText: 'Email', prefixIcon: Icon(Icons.email_outlined),
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _password,
                obscureText: _hidePassword,
                decoration: InputDecoration(
                  labelText: 'Mot de passe',
                  prefixIcon: const Icon(Icons.lock_outline),
                  border: const OutlineInputBorder(),
                  suffixIcon: IconButton(
                    icon: Icon(_hidePassword ? Icons.visibility : Icons.visibility_off),
                    onPressed: () => setState(() => _hidePassword = !_hidePassword),
                  ),
                ),
              ),
              if (auth.state.error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 8),
                  child: Text(auth.state.error!, style: const TextStyle(color: Colors.redAccent)),
                ),
              const SizedBox(height: 24),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: auth.state.loading ? null : () async {
                    await auth.login(_email.text.trim(), _password.text);
                  },
                  child: auth.state.loading
                    ? const CircularProgressIndicator()
                    : const Text('Se connecter'),
                ),
              ),
              const SizedBox(height: 8),
              TextButton.icon(
                onPressed: () => context.go('/login/biometric'),
                icon: const Icon(Icons.face),
                label: const Text('Connexion biométrique'),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
