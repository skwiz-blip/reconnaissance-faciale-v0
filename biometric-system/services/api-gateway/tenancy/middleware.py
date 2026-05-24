"""
Middleware tenant — pose le TenantContext au début de chaque requête HTTP.

Le middleware ne lève pas d'erreur si pas de tenant : c'est aux endpoints
qui en exigent un d'appeler `require_tenant()`. Cela permet aux endpoints
publics (health, metrics, docs) de continuer à fonctionner.
"""
from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from tenancy.context import set_current_tenant
from tenancy.resolver import resolve_tenant_from_request


# Routes ignorées (publiques, jamais multi-tenant)
_SKIP_PREFIXES = (
    "/health", "/metrics", "/docs", "/redoc", "/openapi.json",
    "/api/v1/auth/", "/api/v1/stats", "/ws/",
    "/api/v1/compliance/",  # admin global
    "/api/v1/audit",        # admin global
    "/",
)


class TenantMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Reset (sécurité — éviter les fuites entre requêtes)
        set_current_tenant(None)

        if not any(request.url.path == "/" or request.url.path.startswith(p)
                   for p in _SKIP_PREFIXES if p != "/") and request.url.path != "/":
            try:
                ctx = await resolve_tenant_from_request(request)
                if ctx:
                    set_current_tenant(ctx)
            except Exception:
                pass

        try:
            return await call_next(request)
        finally:
            set_current_tenant(None)
