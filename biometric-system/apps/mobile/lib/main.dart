import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import 'api/auth_repository.dart';
import 'state/auth_provider.dart';
import 'screens/login_screen.dart';
import 'screens/home_screen.dart';
import 'screens/scan_screen.dart';
import 'screens/kyc_screen.dart';
import 'screens/biometric_login_screen.dart';

void main() {
  runApp(const ProviderScope(child: BiometricApp()));
}

class BiometricApp extends ConsumerWidget {
  const BiometricApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final router = ref.watch(routerProvider);
    return MaterialApp.router(
      title: 'Biometric Mobile',
      debugShowCheckedModeBanner: false,
      routerConfig: router,
      theme: ThemeData(
        useMaterial3: true,
        colorScheme: ColorScheme.fromSeed(
          seedColor: const Color(0xFF6366F1),
          brightness: Brightness.dark,
        ),
        scaffoldBackgroundColor: const Color(0xFF0F172A),
        fontFamily: 'Roboto',
      ),
    );
  }
}

final routerProvider = Provider<GoRouter>((ref) {
  final auth = ref.watch(authStateProvider);

  return GoRouter(
    initialLocation: '/',
    refreshListenable: ref.read(authNotifierProvider.notifier),
    redirect: (context, state) {
      final loggedIn = auth.user != null;
      final loggingIn = state.matchedLocation == '/login' ||
                        state.matchedLocation == '/login/biometric';
      if (!loggedIn && !loggingIn) return '/login';
      if (loggedIn && loggingIn) return '/';
      return null;
    },
    routes: [
      GoRoute(path: '/login', builder: (_, __) => const LoginScreen()),
      GoRoute(path: '/login/biometric', builder: (_, __) => const BiometricLoginScreen()),
      GoRoute(path: '/',     builder: (_, __) => const HomeScreen()),
      GoRoute(path: '/scan', builder: (_, __) => const ScanScreen()),
      GoRoute(path: '/kyc',  builder: (_, __) => const KYCScreen()),
    ],
  );
});
