# Biometric Recognition System

Système IA de reconnaissance faciale biométrique professionnel.
**Phase 6** — Multi-tenant SaaS, voix (Resemblyzer 256D), fusion multimodale visage+voix, émotions FER+, stress, active learning, drift detection, webhooks signés HMAC, SDK Python

---

## 🚀 Démarrage rapide

### 1. Prérequis
- Python 3.11+
- Docker & Docker Compose
- Compte Supabase (déjà configuré)

### 2. Configuration
```bash
cp .env.example .env
# Éditer .env et ajouter ta SUPABASE_SERVICE_KEY
# (Settings > API > service_role dans le dashboard Supabase)
```

### 3. Base de données Supabase
Dans le **SQL Editor** de ton dashboard Supabase, exécuter dans l'ordre :
```
supabase/migrations/001_initial_schema.sql
supabase/migrations/002_phase2_auth_clusters.sql
supabase/migrations/003_phase3_kyc_access.sql
supabase/migrations/004_phase5_rgpd_encryption.sql
supabase/migrations/005_phase6_saas_ai.sql
```
Crée toutes les tables + index pgvector + RPC + auth/audit + zones/politiques + challenges + consents/erasure/retention + chiffrement + multi-tenant/voice/affect/webhooks/learning.

### 3.bis Tesseract (OCR KYC)
La Phase 3 utilise Tesseract pour l'OCR documents.
```bash
# Linux
sudo apt-get install -y tesseract-ocr tesseract-ocr-fra
# macOS
brew install tesseract tesseract-lang
# Windows
# → https://github.com/UB-Mannheim/tesseract/wiki
```

### 4. Installation Python
```bash
pip install -r requirements.txt
```

### 5. Lancer l'API
```bash
cd services/api-gateway
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 6. Ou via Docker
```bash
docker compose up --build
```

---

## 📡 API Endpoints

Toutes les routes `/api/v1/*` (hors `/auth/*`) exigent un **JWT Bearer token**.

### Authentification
| Méthode | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/api/v1/auth/register` | Créer un compte (premier = admin) | — |
| POST | `/api/v1/auth/login` | Login → access + refresh tokens | — |
| POST | `/api/v1/auth/refresh` | Rotation refresh → nouveau couple | — |
| POST | `/api/v1/auth/logout` | Révoque l'access token | user |
| GET  | `/api/v1/auth/me` | Profil utilisateur courant | user |

### Reconnaissance
| Méthode | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/api/v1/recognize` | Reconnaissance base64 | user |
| POST | `/api/v1/recognize/upload` | Reconnaissance upload | user |

### Identités
| Méthode | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/api/v1/identities` | Créer identité | admin |
| GET  | `/api/v1/identities` | Lister identités | user |
| GET  | `/api/v1/identities/{id}` | Détail identité | user |
| PATCH | `/api/v1/identities/{id}` | Mettre à jour | user |
| DELETE | `/api/v1/identities/{id}` | Supprimer + évincer FAISS | admin |
| POST | `/api/v1/identities/{id}/enroll` | Enrôler visage (base64) | user |
| POST | `/api/v1/identities/{id}/enroll/upload` | Enrôler visage (fichier) | user |

### Inconnus & Clusters
| Méthode | Endpoint | Description | Auth |
|---|---|---|---|
| GET  | `/api/v1/unknowns` | Liste inconnus pendants | user |
| POST | `/api/v1/unknowns/{id}/resolve` | Résoudre → identité + FAISS | admin |
| POST | `/api/v1/clusters/run` | Lancer DBSCAN manuellement | admin |
| GET  | `/api/v1/clusters` | Liste des clusters | admin |
| GET  | `/api/v1/clusters/{id}/faces` | Visages d'un cluster | admin |
| POST | `/api/v1/clusters/{id}/merge` | Fusionner cluster → identité | admin |

### Temps réel
| Méthode | Endpoint | Description | Auth |
|---|---|---|---|
| WS | `/ws/camera/{camera_id}?token=...` | Flux caméra reco temps réel | user |
| WS | `/ws/dashboard?token=...` | Feed alertes dashboard | admin/operator |

### Liveness challenges (Phase 3)
| Méthode | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/api/v1/liveness/challenges` | Émet un défi (blink, turn_left…) | user |
| POST | `/api/v1/liveness/challenges/submit` | Soumet une frame | user |
| GET  | `/api/v1/liveness/challenges/{id}` | État du défi | user |

### KYC (Phase 3)
| Méthode | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/api/v1/kyc/sessions` | Démarre une session + défi liveness | user |
| POST | `/api/v1/kyc/sessions/submit` | Pipeline complet (selfie + doc) | user |
| GET  | `/api/v1/kyc/sessions/{id}` | État + verdict | user |

### Contrôle d'accès & zones (Phase 3)
| Méthode | Endpoint | Description | Auth |
|---|---|---|---|
| POST | `/api/v1/access/check` | Vérifie l'accès depuis une image | user |
| GET  | `/api/v1/access/zones` | Liste zones | user |
| POST | `/api/v1/access/zones` | Crée zone | admin |
| PATCH | `/api/v1/access/zones/{id}` | Modifie zone | admin |
| DELETE | `/api/v1/access/zones/{id}` | Supprime zone | admin |
| GET  | `/api/v1/access/policies` | Liste politiques (filtre `zone_id`) | user |
| POST | `/api/v1/access/policies` | Crée politique RBAC | admin |
| DELETE | `/api/v1/access/policies/{id}` | Supprime politique | admin |
| GET  | `/api/v1/access/logs` | Historique décisions (vue) | user |

### Audit (Phase 3)
| Méthode | Endpoint | Description | Auth |
|---|---|---|---|
| GET | `/api/v1/audit` | Logs d'audit (filtres action/actor/target) | admin |

### Système
| Méthode | Endpoint | Description | Auth |
|---|---|---|---|
| GET | `/health` | Santé système | — |
| GET | `/api/v1/stats` | Statistiques + FAISS | — |
| GET | `/docs` | Swagger UI | — |

---

## 🔧 Test rapide

```bash
# 1. Premier compte (auto-promu admin)
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@local","password":"changeMe123!","full_name":"Admin"}'
# → renvoie {"access_token": "...", ...}

TOKEN="<colle ton access_token ici>"

# 2. Créer une identité (admin)
curl -X POST http://localhost:8000/api/v1/identities \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"full_name":"Louis Dupont","email":"louis@example.com","role":"user"}'

# 3. Enrôler un visage
curl -X POST http://localhost:8000/api/v1/identities/{id}/enroll/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@photo.jpg"

# 4. Reconnaissance (FAISS → <1ms si index chaud)
curl -X POST http://localhost:8000/api/v1/recognize/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@test.jpg" \
  -F "check_liveness=false"

# 5. Clustering DBSCAN manuel (admin)
curl -X POST http://localhost:8000/api/v1/clusters/run \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"similarity_threshold":0.65,"min_samples":2}'

# 6. Vérification d'accès (caméra de porte)
curl -X POST http://localhost:8000/api/v1/access/check \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "image_base64": "...",
    "zone_code": "office",
    "access_point": "door_main_01",
    "check_liveness": true
  }'
# → {"decision":"granted","reason":"politique 'office_workdays' validée", ...}

# 7. KYC flow (3 étapes)
# (a) Démarrer une session avec challenge liveness
curl -X POST http://localhost:8000/api/v1/kyc/sessions \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"doc_type":"passport","issue_challenge":true}'
# → {"session_token":"...","challenge":{"challenge_id":"...","action":"blink"}}

# (b) Soumettre selfie + document
curl -X POST http://localhost:8000/api/v1/kyc/sessions/submit \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"session_token":"...","selfie_base64":"...","document_base64":"..."}'
# → {"decision":"approved","confidence":0.87,"face_match_score":0.81, ...}

# 8. Challenge liveness isolé
curl -X POST http://localhost:8000/api/v1/liveness/challenges \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"issued_for":"login"}'
# → {"challenge_id":"...","action":"turn_left", ...}
```

---

## 🧠 Architecture IA

```
Frame/Image
    ↓
FaceDetector (InsightFace buffalo_l)
    ↓ bbox + landmarks + embedding
LivenessDetector (LBP + EAR + optical flow)
    ↓ is_live + score
FaceEmbedder (ArcFace 512D ONNX)
    ↓ vecteur 512D normalisé L2
SearchService — FAISS in-memory (<1ms)
    ├─ HIT → hydratation Redis/Supabase → matches
    └─ MISS → fallback Supabase pgvector → matches
    ↓
PipelineResult → API Response (+ log async event)
```

### Étages de cache & sécurité (Phase 2)

```
┌─────────────────────────────────────────────────────┐
│ HTTP request                                        │
│   → JWT middleware (auth_users + Redis revocation)  │
│   → rate-limit (Redis token-bucket par IP)          │
│   → router                                          │
│       → recognition cache (Redis, sig embedding)    │
│       → FAISS search                                │
│       → Supabase pgvector fallback                  │
└─────────────────────────────────────────────────────┘
```

### Stratégie FAISS

- Au démarrage: reload complet de `face_embeddings` (status=active) en mémoire
- Backend: `IndexFlatIP` (<100k) ou `IndexHNSWFlat` (≥100k) — cosine via embeddings normalisés
- Mutations: **write-through** (Supabase d'abord, FAISS ensuite) au moment de l'enrôlement
- Re-sync périodique (10 min par défaut) — sécurité anti-drift

---

## 📁 Structure projet

```
biometric-system/
├── services/
│   ├── ai-core/
│   │   ├── detector.py            # Détection InsightFace
│   │   ├── embedder.py            # Embeddings ArcFace
│   │   ├── anti_spoof.py          # Liveness v1
│   │   ├── liveness_v2.py         # Liveness avancé + challenges  ← Phase 3
│   │   ├── clustering.py          # DBSCAN inconnus
│   │   ├── pipeline.py            # Orchestrateur reco
│   │   └── kyc/                   # ← Phase 3
│   │       ├── document_classifier.py
│   │       ├── ocr.py             # Tesseract + EasyOCR
│   │       ├── mrz.py             # Parser ICAO 9303
│   │       ├── face_match.py
│   │       ├── fraud_detection.py # ELA, Moiré, dates
│   │       └── pipeline.py        # Verdict KYC
│   └── api-gateway/
│       ├── main.py
│       ├── config.py
│       ├── tasks.py               # Celery
│       ├── auth/                  # JWT + RBAC
│       ├── database/              # Supabase + FAISS + Redis
│       ├── services/              # search_service
│       ├── access/                # ← Phase 3
│       │   └── policy_engine.py   # Décision granted/denied/alert
│       ├── middleware/            # ← Phase 3
│       │   └── audit.py           # Audit non bloquant
│       ├── routers/
│       │   ├── auth.py
│       │   ├── recognize.py
│       │   ├── identity.py
│       │   ├── clusters.py
│       │   ├── websocket.py
│       │   ├── kyc.py             # ← Phase 3
│       │   ├── liveness.py        # ← Phase 3
│       │   ├── access.py          # ← Phase 3
│       │   └── audit.py           # ← Phase 3
│       └── models/
│           ├── schemas.py
│           └── schemas_v3.py      # ← Phase 3
├── supabase/migrations/
│   ├── 001_initial_schema.sql
│   ├── 002_phase2_auth_clusters.sql
│   └── 003_phase3_kyc_access.sql
├── apps/                              ← Phase 4
│   ├── dashboard/         # React + Vite + TS + Tailwind
│   │   ├── src/
│   │   │   ├── api/{client,endpoints,types}.ts
│   │   │   ├── auth/AuthContext.tsx
│   │   │   ├── components/{Layout,Sidebar,Topbar,ProtectedRoute,StatCard}.tsx
│   │   │   └── pages/{Login,Dashboard,LiveFeed,Identities,Unknowns,Clusters,Access,KYC,Audit}Page.tsx
│   │   ├── Dockerfile + nginx.conf
│   │   └── vite.config.ts
│   └── mobile/            # Flutter app
│       ├── lib/
│       │   ├── main.dart                          (GoRouter + Riverpod)
│       │   ├── api/{api_client,token_storage,auth_repository,biometric_repository}.dart
│       │   ├── state/auth_provider.dart
│       │   └── screens/{login,biometric_login,home,scan,kyc}_screen.dart
│       └── pubspec.yaml
└── ...
```

## 🖥️ Lancement complet (full stack)

```bash
docker compose up --build
# → API       http://localhost:8000
# → Dashboard http://localhost:5173
# → Metrics   http://localhost:8000/metrics
# → Redis     localhost:6379
```

Première utilisation:
1. Ouvrir le dashboard, **"Créer le premier compte"** → admin auto
2. Aller dans **Identités** → créer + enroller un visage
3. Aller dans **Live Feed** → autoriser webcam, voir la reco en temps réel

## ☸️ Déploiement Kubernetes

Voir [infra/k8s/README.md](infra/k8s/README.md). En résumé :

```bash
kubectl apply -f infra/k8s/namespace.yaml
kubectl apply -f infra/k8s/configmap.yaml
# Préparer infra/k8s/secrets.yaml depuis le template (NE PAS commiter)
kubectl apply -f infra/k8s/secrets.yaml
kubectl apply -f infra/k8s/redis.yaml -f infra/k8s/api.yaml \
              -f infra/k8s/worker.yaml -f infra/k8s/dashboard.yaml \
              -f infra/k8s/ingress.yaml
```

## 🔒 Sécurité / RGPD

```bash
# Générer une clé de chiffrement embeddings
python -m security.encryption generate-key
# → 64 chars hex → coller dans EMBEDDING_ENCRYPTION_KEY

# Effacer une identité (RGPD Art. 17)
curl -X POST .../api/v1/compliance/identities/{id}/erase \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -d '{"reason":"user_request"}'

# Exporter les données (RGPD Art. 15/20)
curl .../api/v1/compliance/identities/{id}/export \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -o export.json

# Lancer la rétention manuellement
curl -X POST .../api/v1/compliance/retention/run \
     -H "Authorization: Bearer $ADMIN_TOKEN"
```

## 🏢 SaaS multi-tenant (Phase 6)

```bash
# 1. Créer un tenant
curl -X POST .../api/v1/tenants \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -d '{"code":"acme-corp","name":"Acme Corp","plan":"pro"}'

# 2. Créer une API key (à donner au partenaire — affichée UNE SEULE FOIS)
curl -X POST .../api/v1/tenants/<tenant_id>/api-keys \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -d '{"name":"prod-key-1","scopes":["recognize","access"]}'
# → "api_key": "bio_xxxxxxxxxxxxx..."

# 3. Le partenaire utilise sa clé:
curl -X POST .../api/v1/recognize -H "X-API-Key: bio_xxx" -d '{...}'
```

### SDK Python (côté partenaire)

```python
from biometric_sdk import BiometricClient

client = BiometricClient(api_url="https://api.example.com", api_key="bio_xxx")
resp = client.recognize_from_file("photo.jpg", check_liveness=True)
for m in resp.matches:
    print(m.full_name, m.similarity)
```

### Webhooks

```bash
# Le partenaire s'abonne aux événements depuis son compte tenant
curl -X POST .../api/v1/webhooks \
     -H "X-API-Key: bio_xxx" \
     -d '{
       "url":"https://partner.example.com/hook",
       "events":["recognition.matched","access.denied","kyc.approved"]
     }'
# → réponse contient "secret": "whsec_xxx" (à stocker côté partenaire)
```

Côté partenaire, vérifier la signature avec `biometric_sdk.verify_webhook_signature(secret, body, header_signature)`.

---

## 🗄️ Tables Supabase

| Table | Description |
|-------|-------------|
| `identities` | Personnes enregistrées (biométrie) |
| `face_embeddings` | Vecteurs 512D (pgvector) |
| `unknown_faces` | Inconnus en attente (+ `cluster_id`) |
| `recognition_events` | Journal détections |
| `access_logs` | Journal accès |
| `kyc_sessions` | Sessions KYC (+ MRZ, OCR, fraud, decision) |
| `cameras` | Caméras enregistrées |
| `auth_users` | Comptes admin/opérateur (Phase 2) |
| `audit_logs` | Trace actions sensibles (Phase 2) |
| `zones` | Zones contrôlées (Phase 3) |
| `access_policies` | Politiques RBAC par zone (Phase 3) |
| `access_points` | Points d'accès ↔ zones (Phase 3) |
| `liveness_challenges` | Défis émis et résolutions (Phase 3) |

RPC: `search_face`, `search_unknown_faces`, `search_face_in_cluster`, `list_clusters`, `increment_unknown_appearances`, `cleanup_expired_challenges`.
Vue: `access_summary` (jointure access_logs × identities × events).

---

## ⚠️ Sécurité

- Utiliser la **service_role key** (jamais l'anon key) côté backend
- Le RLS est activé sur toutes les tables
- Les embeddings biométriques sont stockés chiffrés en production
- Activer HTTPS en production (certificat Let's Encrypt)

---

## ✅ Phase 2 livrée

- [x] FAISS in-memory (FlatIP < 100k, HNSW ≥ 100k) avec write-through + re-sync
- [x] Redis cache (résultats reco, identités, refresh tokens, rate-limit, révocation JWT)
- [x] JWT auth + RBAC (admin / operator / viewer) + refresh token rotation
- [x] Clustering DBSCAN inconnus (manuel via API + Celery périodique)
- [x] WebSocket sécurisé (JWT via `?token=` ou header)
- [x] Health check étendu (FAISS + Redis)

## ✅ Phase 6 livrée

### Multi-tenant SaaS — [services/api-gateway/tenancy/](services/api-gateway/tenancy/)
- `TenantMiddleware` qui pose un `TenantContext` (ContextVar coroutine-safe) à chaque requête
- Résolution via `X-API-Key` (tenant key SHA-256 hashed) ou `X-Tenant-Id` (slug/uuid + JWT)
- Cache Redis 60s sur tenants + API keys
- Quotas + plans (free/pro/enterprise) + table `tenant_usage_daily` + RPC `increment_tenant_usage`
- CRUD complet via `/api/v1/tenants` (admin only) + génération API keys

### Reconnaissance vocale — [services/ai-core/voice/](services/ai-core/voice/)
- [embedder.py](services/ai-core/voice/embedder.py) — Resemblyzer GE2E 256-D, mock fallback si paquet absent
- [fusion.py](services/ai-core/voice/fusion.py) — 4 stratégies (weighted_sum / min / max / product), require_both, défaut 0.6 visage + 0.4 voix
- Router [/api/v1/voice](services/api-gateway/routers/voice.py) : enroll / verify (1:1) / identify (1:N pgvector HNSW 256D) / fuse
- Table `voice_embeddings` + RPC `search_voice` scopé tenant

### Affect (émotions + stress) — [services/ai-core/affect/](services/ai-core/affect/)
- [emotion.py](services/ai-core/affect/emotion.py) — FER+ ONNX (8 émotions Ekman), fallback heuristique landmarks
- [stress.py](services/ai-core/affect/stress.py) — fenêtre 30s : blink rate + variance pose + émotions négatives + asymétrie
- Router [/api/v1/affect](services/api-gateway/routers/affect.py) : emotion (image) / stress (séquence) / timeline (séries temporelles)
- Table `affect_signals` reliée aux events

### Active learning + drift — [services/api-gateway/learning/](services/api-gateway/learning/)
- [active_learning.py](services/api-gateway/learning/active_learning.py) — capture auto des matches "borderline" (0.55-0.72), file de validation admin, 3 corrections (confirm/reassign/reject)
- [drift.py](services/api-gateway/learning/drift.py) — calcule cohésion baseline + similarité récents → centroïde, scheduling re-enrôlement auto (poids 0.6 pour ne pas écraser la baseline)
- Router [/api/v1/learning](services/api-gateway/routers/learning.py) : corrections (list/apply) + drift/{identity_id}
- Hook automatique dans le pipeline (tout match < 0.72 alimente la queue)

### Webhooks — [services/api-gateway/webhooks/](services/api-gateway/webhooks/)
- Style Stripe : `X-Bio-Signature: t=<ts>,v1=<hmac_sha256(ts.body)>` + tolérance 5 min replay
- 3 retries avec backoff exponentiel (1s, 4s, 16s), persistance `webhook_deliveries`
- **12 event types** (`recognition.matched`, `access.denied`, `kyc.approved`, etc.)
- Dispatch auto depuis le pipeline (fire-and-forget)
- Router [/api/v1/webhooks](services/api-gateway/routers/webhooks.py) : CRUD + deliveries + test endpoint (tenant-aware)

### Python SDK — [sdks/python/](sdks/python/)
- Client sync + async (httpx)
- 3 exceptions typées (`AuthenticationError`, `RateLimitError`, `ApiError`)
- Helpers `recognize_from_file`, `check_access`, `start_kyc/submit_kyc`, `create_identity`, `enroll_face`
- `verify_webhook_signature()` exposé pour les partenaires côté serveur
- Packageable `pip install -e sdks/python`

### SQL Migration 005 — [005_phase6_saas_ai.sql](supabase/migrations/005_phase6_saas_ai.sql)
9 nouvelles tables : `tenants`, `tenant_api_keys`, `voice_embeddings`, `affect_signals`, `webhooks`, `webhook_deliveries`, `correction_candidates`, `drift_reports`, `tenant_usage_daily`. Ajout `tenant_id` sur 8 tables existantes. 3 RPC. Vue `tenant_overview`.

## ✅ Phase 5 livrée

### Performance GPU & batch
- [services/ai-core/gpu_runtime.py](services/ai-core/gpu_runtime.py) — détection auto (TensorRT > CUDA > CoreML > CPU), métriques inférence, preprocessing batch ArcFace
- [services/ai-core/embedder.py](services/ai-core/embedder.py) — `embed_batch()` (gain 3-5× sur GPU), warmup au démarrage, optimisation graph ONNX `ORT_ENABLE_ALL`

### Chiffrement biométrique (AES-256-GCM)
- [services/api-gateway/security/encryption.py](services/api-gateway/security/encryption.py) — clé via env (hex/base64) ou dérivée PBKDF2 200k itérations
- Format stockage: `base64(nonce[12] || ciphertext || tag[16])` dans `face_embeddings.embedding_encrypted`
- Déchiffrement transparent au reload FAISS (vecteurs en RAM en clair pour la recherche, repos chiffré)
- CLI: `python -m security.encryption generate-key`

### Conformité RGPD complète
- [compliance/rgpd.py](services/api-gateway/compliance/rgpd.py) — Art. 15 / 17 / 20 / 7
  - **Effacement** : suppression cascade + anonymisation logs + éviction FAISS + audit trail
  - **Export portable** : dump JSON streamé (identité + embeddings + events + access + KYC + consents)
  - **Consentement** : table `consents` avec historique horodaté + IP/UA
- [compliance/retention.py](services/api-gateway/compliance/retention.py) — politiques par défaut: events 90j, access 180j, unknowns 30j, audit 730j, KYC rejected 30j
- Tâche Celery quotidienne `retention_pass_task` (cron 03:00 UTC)
- Router [/api/v1/compliance/*](services/api-gateway/routers/compliance.py) (admin only)

### Observabilité Prometheus
- [observability/metrics.py](services/api-gateway/observability/metrics.py) — middleware `/metrics`
- **9 métriques** : `bio_http_requests_total`, `bio_http_request_duration_seconds`, `bio_recognition_total`, `bio_access_decisions_total`, `bio_kyc_decisions_total`, `bio_faiss_search_seconds`, `bio_embedding_inference_seconds`, `bio_websocket_connections`
- Normalisation des paths (`/identities/:id`) pour éviter l'explosion cardinale

### Kubernetes production-ready
- [infra/k8s/](infra/k8s/) — namespace, ConfigMap, Secret (template), API (HPA 2-10, PDB, anti-affinity, GPU optionnel via `nvidia.com/gpu`), Worker + Beat Celery, Redis StatefulSet, Dashboard, Ingress + cert-manager
- Annotations Prometheus pour scraping auto
- Multi-AZ via podAntiAffinity, rolling update zero-downtime

### Load testing Locust
- [tests/load/locustfile.py](tests/load/locustfile.py) — 4 scénarios pondérés (login 20% / recognize 60% / access 15% / admin 5%)
- 4 profils documentés (smoke / nominal / stress / soak)
- SLO recommandés par endpoint

### CI/CD GitHub Actions
- [.github/workflows/ci.yml](.github/workflows/ci.yml) — lint Python (black + isort) + tests + build dashboard + Docker push GHCR + Trivy scan
- [.github/workflows/release.yml](.github/workflows/release.yml) — release sur tag `v*.*.*` (multi-arch amd64+arm64)
- [.github/workflows/load-test.yml](.github/workflows/load-test.yml) — load test manuel paramétrable

### SQL Migration 004
- [004_phase5_rgpd_encryption.sql](supabase/migrations/004_phase5_rgpd_encryption.sql) — colonnes `embedding_encrypted`, tables `consents` / `erasure_requests` / `retention_runs`, RPC `anonymize_old_logs`, vues `identity_compliance_view` / `recognition_events_hourly`

## ✅ Phase 4 livrée

### Dashboard React — [apps/dashboard](apps/dashboard)
- Vite + React 18 + TypeScript + Tailwind + TanStack Query + Recharts
- Auth JWT avec refresh rotation automatique sur 401
- **9 pages** : Login, Dashboard (stats + graphique décisions), Live Feed (WebSocket caméra), Identités (CRUD + enroll), Inconnus, Clusters (DBSCAN + fusion), Accès (4 onglets: logs/zones/politiques/check), KYC, Audit
- WebSocket caméra avec capture webcam + envoi N fps + overlay résultats
- Docker multi-stage nginx prêt + service dans `docker-compose.yml`

### App mobile Flutter — [apps/mobile](apps/mobile)
- Flutter 3.22 + Riverpod + go_router + Dio + flutter_secure_storage
- **5 écrans** : Login, Login biométrique (empreinte/Face ID device), Home, Scan (caméra/galerie → reco), KYC (selfie + doc → verdict)
- Refresh JWT automatique côté Dio
- Stockage tokens chiffré (Keychain iOS / EncryptedSharedPrefs Android)

## ✅ Phase 3 livrée

- [x] **Anti-spoofing v2** : LBP réelle, color consistency, Moiré, glints oculaires, EAR, head pose, smile/mouth detection — `services/ai-core/liveness_v2.py`
- [x] **Analyse de séquence** (`SequenceAnalyzer`) — agrège N frames, exige clignement OU mouvement de tête
- [x] **Challenge-response** (`ChallengeEvaluator`) — blink, turn left/right, look up/down, smile, open mouth — 7 actions
- [x] **Pipeline KYC complet** — `services/ai-core/kyc/`
  - `document_classifier.py` : détection passeport / CI / permis via aspect ratio + MRZ
  - `ocr.py` : Tesseract + EasyOCR fallback + extraction de champs (regex)
  - `mrz.py` : parser ICAO TD1/TD2/TD3 avec validation checksums
  - `face_match.py` : selfie ↔ doc, seuil KYC 0.70 (vs 0.60 reco)
  - `fraud_detection.py` : ELA, Moiré, blur, dates, checksums MRZ, doc mismatch
  - `pipeline.py` : verdict APPROVED / REVIEW / REJECTED + score consolidé
- [x] **Policy engine RBAC** — `services/api-gateway/access/policy_engine.py`
  - Rôles × jours × horaires × liveness × similarité min × anti-tailgating
  - Décisions GRANTED / DENIED / ALERT
  - Cache Redis 60s sur zones + politiques
- [x] **Audit middleware** non bloquant — `services/api-gateway/middleware/audit.py`
  - Trace POST/PUT/PATCH/DELETE sur routes sensibles
  - Action normalisée (`identities.delete`, `kyc.approved`, ...)
- [x] **Tables Phase 3** : `zones`, `access_policies`, `liveness_challenges`, `access_points` + extension `kyc_sessions` + vue `access_summary`
- [x] **9 nouveaux endpoints** KYC / liveness / access / audit + seed de 4 zones de démo

## 🎯 Roadmap suivante (Phase 7+)

- [ ] SDK JavaScript / TypeScript (web + Node)
- [ ] SDK Java/Kotlin (Android natif)
- [ ] rPPG (variabilité cardiaque depuis vidéo) pour stress avancé
- [ ] Identification comportementale (démarche, posture via OpenPose)
- [ ] Fine-tuning continu effectif (LoRA sur ArcFace avec batch hebdomadaire)
- [ ] Edge inference (ONNX → Triton / NVIDIA Jetson)
- [ ] Marketplace tenants + portail self-service signup
- [ ] SSO entreprise (SAML 2.0, OIDC)
