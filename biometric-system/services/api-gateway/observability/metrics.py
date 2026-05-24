"""
Métriques Prometheus exposées sur /metrics.

Compteurs:
    bio_http_requests_total{method, path, status}
    bio_recognition_total{event_type}
    bio_access_decisions_total{decision}
    bio_kyc_decisions_total{decision}
    bio_websocket_connections (gauge)

Histogrammes (latence):
    bio_http_request_duration_seconds{method, path}
    bio_faiss_search_seconds
    bio_embedding_inference_seconds
"""
from __future__ import annotations

import time

from fastapi import Request, Response
from prometheus_client import (
    CollectorRegistry, Counter, Gauge, Histogram,
    CONTENT_TYPE_LATEST, generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware


REGISTRY = CollectorRegistry()

# ----- HTTP -----
http_requests_total = Counter(
    "bio_http_requests_total", "Total HTTP requests",
    labelnames=("method", "path", "status"),
    registry=REGISTRY,
)
http_request_duration_seconds = Histogram(
    "bio_http_request_duration_seconds", "HTTP request latency",
    labelnames=("method", "path"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)

# ----- Reconnaissance -----
recognition_total = Counter(
    "bio_recognition_total", "Total recognition pipeline runs",
    labelnames=("event_type",),  # recognized | unknown | spoof_detected | rejected
    registry=REGISTRY,
)
faiss_search_seconds = Histogram(
    "bio_faiss_search_seconds", "FAISS search latency",
    buckets=(0.0005, 0.001, 0.002, 0.005, 0.01, 0.025, 0.05, 0.1),
    registry=REGISTRY,
)
embedding_inference_seconds = Histogram(
    "bio_embedding_inference_seconds", "Embedding inference latency (per face)",
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5),
    registry=REGISTRY,
)

# ----- WebSocket -----
websocket_connections = Gauge(
    "bio_websocket_connections", "Active WebSocket connections",
    labelnames=("kind",),  # camera | dashboard
    registry=REGISTRY,
)

# ----- Décisions métier -----
access_decisions_total = Counter(
    "bio_access_decisions_total", "Access decisions",
    labelnames=("decision",),
    registry=REGISTRY,
)
kyc_decisions_total = Counter(
    "bio_kyc_decisions_total", "KYC decisions",
    labelnames=("decision",),
    registry=REGISTRY,
)


# ============================================================
# Middleware
# ============================================================

# Normalisation des chemins pour éviter l'explosion cardinale
# Ex: /api/v1/identities/{id} → /api/v1/identities/:id
_PATH_TEMPLATES: list[tuple[str, str]] = [
    ("/api/v1/identities/",       "/api/v1/identities/:id"),
    ("/api/v1/unknowns/",         "/api/v1/unknowns/:id"),
    ("/api/v1/clusters/",         "/api/v1/clusters/:id"),
    ("/api/v1/kyc/sessions/",     "/api/v1/kyc/sessions/:id"),
    ("/api/v1/access/zones/",     "/api/v1/access/zones/:id"),
    ("/api/v1/access/policies/",  "/api/v1/access/policies/:id"),
    ("/api/v1/liveness/challenges/", "/api/v1/liveness/challenges/:id"),
    ("/ws/camera/",               "/ws/camera/:id"),
]


def _template(path: str) -> str:
    for prefix, tmpl in _PATH_TEMPLATES:
        if path.startswith(prefix) and path != prefix.rstrip("/"):
            # path = /api/v1/identities/<uuid>[/anything]
            suffix = path[len(prefix):]
            # Si /enroll, /resolve, etc. → ajoute la sous-action
            if "/" in suffix:
                tail = "/" + suffix.split("/", 1)[1]
                return tmpl + tail
            return tmpl
    return path


class PrometheusMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = _template(request.url.path)
        method = request.method
        t0 = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            elapsed = time.perf_counter() - t0
            http_requests_total.labels(method=method, path=path, status=str(status)).inc()
            http_request_duration_seconds.labels(method=method, path=path).observe(elapsed)


# ============================================================
# Exposition
# ============================================================

def metrics_text() -> Response:
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
