"""Observabilité: métriques Prometheus + logs structurés."""
from observability.metrics import (
    REGISTRY, metrics_text,
    http_requests_total, http_request_duration_seconds,
    recognition_total, faiss_search_seconds, embedding_inference_seconds,
    websocket_connections, access_decisions_total, kyc_decisions_total,
    PrometheusMiddleware,
)

__all__ = [
    "REGISTRY", "metrics_text",
    "http_requests_total", "http_request_duration_seconds",
    "recognition_total", "faiss_search_seconds", "embedding_inference_seconds",
    "websocket_connections", "access_decisions_total", "kyc_decisions_total",
    "PrometheusMiddleware",
]
