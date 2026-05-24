# Biometric Mobile App (Flutter)

App Flutter compagnon du système biométrique.
Fonctionnalités MVP : login email/password, login biométrique (empreinte/visage device),
scan visage pour reconnaissance, flow KYC complet (selfie + document).

## Pré-requis
- Flutter SDK ≥ 3.22
- Android Studio ou Xcode pour les builds natifs

## Configuration

L'URL de l'API est résolue dans cet ordre :
1. `--dart-define=API_URL=https://api.your-domain.com`
2. Par défaut : `http://10.0.2.2:8000` (émulateur Android → host machine)

```bash
flutter pub get
flutter run --dart-define=API_URL=http://192.168.1.10:8000
```

## Permissions natives à ajouter

### Android (`android/app/src/main/AndroidManifest.xml`)
```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.CAMERA" />
<uses-permission android:name="android.permission.USE_BIOMETRIC" />
<uses-feature android:name="android.hardware.camera"  android:required="false" />
```

### iOS (`ios/Runner/Info.plist`)
```xml
<key>NSCameraUsageDescription</key>
<string>Caméra requise pour la reconnaissance biométrique</string>
<key>NSFaceIDUsageDescription</key>
<string>Authentification biométrique de l'app</string>
<key>NSPhotoLibraryUsageDescription</key>
<string>Sélection de photos pour le KYC</string>
```

Sur iOS, `local_auth` exige aussi dans `ios/Runner/Info.plist` :
```xml
<key>NSFaceIDUsageDescription</key>
<string>…</string>
```

## Architecture

```
lib/
├── main.dart                # ProviderScope + GoRouter
├── api/
│   ├── api_client.dart      # Dio + refresh JWT
│   ├── token_storage.dart   # flutter_secure_storage
│   ├── auth_repository.dart
│   └── biometric_repository.dart
├── state/
│   └── auth_provider.dart   # Riverpod
└── screens/
    ├── login_screen.dart
    ├── biometric_login_screen.dart
    ├── home_screen.dart
    ├── scan_screen.dart
    └── kyc_screen.dart
```

## TODO (Phase 5+)
- Live camera continue avec préview + envoi WS (au lieu d'image_picker)
- Push notifications (FCM) sur alertes ALERT/DENIED
- Mode hors-ligne avec sync différée
- Liaison biométrie device → refresh_token (déverrouillage rapide)
