# Load testing

Tests de charge avec Locust.

## Pré-requis

```bash
pip install locust
mkdir -p tests/load/fixtures
# Placer une image de visage valide à fixtures/face.jpg
```

## Lancement local

```bash
cd tests/load
locust -f locustfile.py --host http://localhost:8000
# → http://localhost:8089
```

## Lancement headless (CI)

```bash
locust -f tests/load/locustfile.py \
    --host http://localhost:8000 \
    --headless --users 50 --spawn-rate 5 \
    --run-time 5m --csv=results/run
```

## Profils de charge recommandés

| Profil | Users | Spawn | Durée | Objectif |
|---|---|---|---|---|
| Smoke | 5 | 1 | 1m | sanity check |
| Charge nominale | 50 | 5 | 10m | p95 < 200ms |
| Stress | 200 | 20 | 5m | identifier le point de rupture |
| Soak | 100 | 10 | 1h | détection fuites mémoire |

## Seuils SLO recommandés

| Endpoint | Cible p95 |
|---|---|
| GET /stats | < 50 ms |
| POST /recognize | < 250 ms (CPU) / < 80 ms (GPU) |
| POST /access/check | < 350 ms |
| POST /auth/login | < 400 ms |
