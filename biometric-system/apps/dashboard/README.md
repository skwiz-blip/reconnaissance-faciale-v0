# Biometric Dashboard (React + Vite)

Console admin/opérateur du système biométrique.
Couvre toutes les fonctionnalités Phase 1-3 : reconnaissance temps réel, gestion identités,
inconnus & clusters, contrôle d'accès, KYC, audit.

## Pré-requis
- Node.js ≥ 20
- Backend FastAPI démarré sur `http://localhost:8000`

## Démarrage local

```bash
cd apps/dashboard
npm install
npm run dev
# → http://localhost:5173
```

Le serveur Vite proxifie `/api`, `/ws`, `/health` vers `localhost:8000`.

## Variables d'environnement

`.env.local` (optionnel) :
```env
VITE_API_URL=https://api.your-domain.com/
```

Si vide, le proxy Vite (dev) ou nginx (prod, image Docker) prend le relais.

## Build production

```bash
npm run build
# → dist/ servi par n'importe quel host statique
```

Image Docker prête : `apps/dashboard/Dockerfile` (build multi-stage nginx).
Activée par défaut dans le `docker-compose.yml` racine.

## Architecture

```
src/
├── main.tsx              # bootstrap React + QueryClient + Auth + Router
├── App.tsx               # routes principales
├── api/
│   ├── client.ts         # axios + interceptor refresh JWT
│   ├── endpoints.ts      # wrappers HTTP
│   └── types.ts          # types miroirs des schémas Pydantic
├── auth/AuthContext.tsx  # session utilisateur
├── components/           # Layout, Sidebar, Topbar, ProtectedRoute, StatCard
├── pages/
│   ├── LoginPage.tsx
│   ├── DashboardPage.tsx          # stats + alertes + graph décisions
│   ├── LiveFeedPage.tsx           # WebSocket caméra
│   ├── IdentitiesPage.tsx         # CRUD + enroll
│   ├── UnknownsPage.tsx           # validation
│   ├── ClustersPage.tsx           # DBSCAN + fusion
│   ├── AccessPage.tsx             # tabs: logs / zones / policies / check
│   ├── KYCPage.tsx                # session + verdict
│   └── AuditPage.tsx              # admin only
└── styles/globals.css    # tailwind + components custom
```

## Auth

- JWT access (15 min) + refresh (30 jours) stockés dans `localStorage`
- Refresh automatique sur 401 (rotation refresh côté backend)
- WebSocket: token passé en query string `?token=…`
- Premier compte enregistré → admin auto
