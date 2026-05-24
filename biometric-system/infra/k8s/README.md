# Kubernetes manifests

Déploiement production du système biométrique sur Kubernetes.

## Architecture

```
biometric (namespace)
├── ConfigMap   biometric-config
├── Secret      biometric-secrets       (NE PAS commiter)
├── Deployment  biometric-api (2-10 replicas, HPA CPU/mem)
├── Deployment  biometric-dashboard (2 replicas, nginx)
├── Deployment  biometric-worker  (Celery worker)
├── Deployment  biometric-beat    (Celery scheduler, 1 replica)
├── StatefulSet biometric-redis   (1 replica, PVC 2Gi)
├── Service     biometric-api, biometric-dashboard, biometric-redis
├── HPA         biometric-api-hpa
├── PDB         biometric-api-pdb (minAvailable=1)
└── Ingress     biometric-ingress (cert-manager TLS)
```

## Pré-requis

- Cluster Kubernetes ≥ 1.27
- `nginx-ingress-controller` installé
- `cert-manager` avec un ClusterIssuer `letsencrypt-prod`
- Pour GPU: NVIDIA device plugin (`nvidia-device-plugin-daemonset`)
- Pour les métriques HPA: `metrics-server`

## Déploiement

```bash
# 1. Construire et pusher les images
docker build -t ghcr.io/your-org/biometric-api:latest      -f infra/docker/Dockerfile.api .
docker build -t ghcr.io/your-org/biometric-dashboard:latest -f apps/dashboard/Dockerfile apps/dashboard
docker push ghcr.io/your-org/biometric-api:latest
docker push ghcr.io/your-org/biometric-dashboard:latest

# 2. Créer le namespace et le ConfigMap
kubectl apply -f infra/k8s/namespace.yaml
kubectl apply -f infra/k8s/configmap.yaml

# 3. Préparer les secrets (à partir du template)
cp infra/k8s/secrets.example.yaml infra/k8s/secrets.yaml
# Remplir secrets.yaml (cf instructions dans le fichier)
kubectl apply -f infra/k8s/secrets.yaml

# 4. Déployer les composants
kubectl apply -f infra/k8s/redis.yaml
kubectl apply -f infra/k8s/api.yaml
kubectl apply -f infra/k8s/worker.yaml
kubectl apply -f infra/k8s/dashboard.yaml
kubectl apply -f infra/k8s/ingress.yaml

# 5. Vérifier
kubectl -n biometric get pods -w
kubectl -n biometric logs deploy/biometric-api --tail=50
```

## Activer GPU

Décommenter `nvidia.com/gpu: 1` dans `api.yaml` (resources.requests + limits)
et mettre `GPU_ENABLED: "true"` dans la ConfigMap (déjà fait).

## Rollout

```bash
kubectl -n biometric set image deploy/biometric-api api=ghcr.io/your-org/biometric-api:v2.1.0
kubectl -n biometric rollout status deploy/biometric-api
# Rollback si pépin
kubectl -n biometric rollout undo deploy/biometric-api
```

## Observabilité

Les annotations Prometheus sur les pods api permettent le scraping automatique
si Prometheus est déployé avec `kubernetes_sd_configs.pod`.
Sinon, créer un `ServiceMonitor` (operator) pointant sur `biometric-api:80/metrics`.
