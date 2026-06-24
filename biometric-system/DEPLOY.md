# Déploiement — Backend Fly.io + Frontend Vercel

Guide complet du dev local au prod en ligne.

```
┌─────────────────┐         HTTPS         ┌──────────────────┐
│  Vercel (CDN)   │ ─────────────────────▶│  Fly.io (Docker) │
│  React/Vite     │                       │  FastAPI + ML    │
│  apps/dashboard │                       │  + Redis Upstash │
└─────────────────┘                       └────────┬─────────┘
                                                   │
                                                   ▼
                                          ┌──────────────────┐
                                          │     Supabase     │
                                          │  Postgres pgvec  │
                                          └──────────────────┘
```

---

## 1 · Backend sur Fly.io

### 1.1 — Installer le CLI

PowerShell :
```powershell
iwr https://fly.io/install.ps1 -useb | iex
```

Recharger le PATH puis :
```powershell
flyctl version
flyctl auth signup     # ou: flyctl auth login
```

(Tu devras ajouter une carte bancaire pour les volumes & VMs > 256MB. Free tier ne couvre pas le besoin RAM de ce projet.)

### 1.2 — Créer l'app

Depuis la racine du projet :

```powershell
cd c:\Users\HP\Documents\Mes_Projects\biometric-system

# Crée l'app — choisis un nom unique (le fly.toml utilise "biometric-api")
flyctl apps create biometric-api-<ton-nom>
# Édite fly.toml ligne `app = "..."` pour matcher
```

### 1.3 — Créer le volume persistant (modèles ONNX)

```powershell
flyctl volumes create biometric_data --size 2 --region cdg
# 2 GB suffisent pour buffalo_l (~280 MB) + arcface + fer+
```

### 1.4 — Configurer Redis (Upstash via Fly)

```powershell
flyctl ext redis create
# → choisis "biometric-api" comme app à attacher
# → région: cdg (même que ta VM)
# → plan: Free (10MB, suffit pour cache + JWT révocation)
```

Cela ajoute automatiquement `REDIS_URL` aux secrets de l'app.

### 1.5 — Injecter les secrets

```powershell
flyctl secrets set `
  SUPABASE_URL="https://iztvgaurvbskjsehjshn.supabase.co" `
  SUPABASE_ANON_KEY="eyJ...ton_anon..." `
  SUPABASE_SERVICE_KEY="eyJ...ton_service_role..." `
  SECRET_KEY="$(python -c 'import secrets;print(secrets.token_hex(32))')" `
  EMBEDDING_ENCRYPTION_ENABLED="false"
```

Pour vérifier :
```powershell
flyctl secrets list
```

### 1.6 — Premier déploiement

```powershell
flyctl deploy
```

Premier build : ~8-10 min (compile cryptography, télécharge PyTorch). Builds suivants : ~2 min.

Quand c'est prêt :
```powershell
flyctl status
flyctl logs            # suivre en direct
flyctl open            # ouvre l'URL dans le navigateur
```

Ton API est sur `https://biometric-api-<ton-nom>.fly.dev`. Test :
```powershell
curl https://biometric-api-<ton-nom>.fly.dev/health
```

### 1.7 — CORS pour Vercel

Une fois ton URL Vercel connue (étape 2.3), ajoute-la aux origins autorisées :

```powershell
flyctl secrets set CORS_ORIGINS="https://reconnaissance-faciale-v0.vercel.app,https://*.vercel.app"
```

L'app redémarre automatiquement.

---

## 2 · Frontend sur Vercel

### 2.1 — Configurer le projet

Sur **vercel.com → ton projet → Settings → General** :

| Champ | Valeur |
|---|---|
| Root Directory | `apps/dashboard` |
| Framework Preset | Vite (détecté auto via `vercel.json`) |
| Build Command | `npm run build` (auto) |
| Output Directory | `dist` (auto) |
| Install Command | `npm install` (auto) |

### 2.2 — Variables d'environnement

**Settings → Environment Variables** :

| Nom | Valeur | Scope |
|---|---|---|
| `VITE_API_URL` | `https://biometric-api-<ton-nom>.fly.dev/` | Production, Preview |

⚠️ Le `/` final est important.

### 2.3 — Déployer

Push sur `main` → Vercel build automatiquement.

Ou en CLI :
```powershell
npm i -g vercel
cd apps\dashboard
vercel --prod
```

URL : `https://reconnaissance-faciale-v0.vercel.app` (ou ton nom de projet)

### 2.4 — Revenir mettre à jour CORS côté backend

Ajoute l'URL exacte de Vercel dans les secrets Fly (étape 1.7).

---

## 3 · Vérifications finales

```powershell
# Backend healthy ?
curl https://biometric-api-<ton-nom>.fly.dev/health

# Dashboard répond ?
curl -I https://reconnaissance-faciale-v0.vercel.app

# Le dashboard arrive à parler à l'API ?
# → Ouvre l'app dans le navigateur, "Créer le premier compte"
# → DevTools Network, regarde l'appel /api/v1/auth/register
# → Doit retourner 201 et stocker access_token
```

---

## 4 · Commandes utiles Fly

```powershell
# Logs en temps réel
flyctl logs

# Console shell dans le container
flyctl ssh console
> uvicorn main:app  # tester manuellement
> ls /data/models    # vérifier le volume

# Redéployer après un changement
flyctl deploy

# Scale (plus de RAM)
flyctl scale vm performance-2x      # 4GB

# Plus de réplicas (haute dispo)
flyctl scale count 2

# Stopper l'app (économise)
flyctl scale count 0

# Voir les coûts en cours
flyctl orgs show personal
```

---

## 5 · Coûts estimés (Fly + Vercel + Supabase + Upstash)

| Service | Plan | Coût/mois |
|---|---|---|
| Vercel Hobby | Free | 0 € |
| Fly performance-1x (2GB, 24/7) | À l'usage | ~5 € |
| Fly volume 2GB | À l'usage | ~0.30 € |
| Upstash Redis 10MB | Free | 0 € |
| Supabase Free | Free | 0 € |
| **Total estimé** | | **~5-7 €/mois** |

Pour économiser : `auto_stop_machines = "stop"` dans `fly.toml` (déjà activé) — la VM s'éteint si pas de trafic 5 min. Cold start ~10s au retour.

---

## 6 · Migrations SQL en prod

Toutes les migrations doivent être exécutées **manuellement** dans le SQL Editor Supabase (dans l'ordre `001` → `005`) avant le premier déploiement du backend, sinon l'API plantera au boot.

---

## 7 · Troubleshooting

| Symptôme | Cause probable | Fix |
|---|---|---|
| `Out of memory killed` au boot | VM 256MB trop petite | `flyctl scale vm performance-1x` |
| `relation "X" does not exist` | Migration SQL manquante | Exécuter `00X_*.sql` sur Supabase |
| `CORS error` côté dashboard | Origine pas dans `CORS_ORIGINS` | Voir étape 1.7 |
| 502 sur `/api/*` | Backend down ou cold start | `flyctl logs` + attendre 10s |
| Modèles re-téléchargés à chaque deploy | Volume mal monté | Vérifier `flyctl volumes list` + mount dans fly.toml |
