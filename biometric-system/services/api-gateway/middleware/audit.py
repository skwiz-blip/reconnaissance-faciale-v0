"""
Middleware d'audit — trace les requêtes mutantes (POST/PUT/PATCH/DELETE)
sur les routes sensibles.

Inséré comme un middleware HTTP standard. Non bloquant: l'écriture en
base se fait dans une coroutine fire-and-forget pour ne pas pénaliser
la latence.

Routes auditées (préfixes):
    /api/v1/identities
    /api/v1/kyc
    /api/v1/access
    /api/v1/clusters
    /api/v1/auth/register
    /api/v1/auth/logout
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import Request
from jose import JWTError
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware

from auth.jwt_handler import decode_token
from database.supabase_client import get_supabase


AUDIT_PREFIXES = (
    "/api/v1/identities",
    "/api/v1/kyc",
    "/api/v1/access",
    "/api/v1/clusters",
    "/api/v1/auth/register",
    "/api/v1/auth/logout",
)
AUDIT_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        if request.method not in AUDIT_METHODS:
            return response
        if not any(request.url.path.startswith(p) for p in AUDIT_PREFIXES):
            return response
        # On n'audit pas les 4xx (sauf 401/403 que les routes refusent déjà)
        if response.status_code >= 400 and response.status_code < 500:
            return response

        actor_id, actor_role = _extract_actor(request)
        action = _derive_action(request)

        asyncio.create_task(_write_audit(
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            path=request.url.path,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            status_code=response.status_code,
        ))
        return response


def _extract_actor(request: Request) -> tuple[Optional[str], Optional[str]]:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None, None
    token = header.split(" ", 1)[1].strip()
    try:
        payload = decode_token(token, expected_type="access")
        return payload.sub, payload.role
    except JWTError:
        return None, None


def _derive_action(request: Request) -> str:
    """Mappe HTTP method + path → string normalisé pour audit_logs.action."""
    path = request.url.path
    method = request.method.lower()
    # Compression: /api/v1/identities/{id}/enroll → identities.enroll
    parts = [p for p in path.split("/") if p and p not in ("api", "v1")]
    # Supprime les UUIDs/IDs (heuristique: contiennent '-' ou hex pure)
    cleaned = [p for p in parts if not _looks_like_id(p)]
    suffix = ".".join(cleaned) if cleaned else "root"
    return f"{suffix}.{method}"


def _looks_like_id(s: str) -> bool:
    if "-" in s and len(s) > 20:
        return True
    if len(s) >= 16 and all(c in "0123456789abcdef" for c in s.lower()):
        return True
    return False


async def _write_audit(
    actor_id: Optional[str],
    actor_role: Optional[str],
    action: str,
    path: str,
    ip: Optional[str],
    user_agent: Optional[str],
    status_code: int,
) -> None:
    try:
        get_supabase().table("audit_logs").insert({
            "actor_id":    actor_id,
            "actor_role":  actor_role,
            "action":      action,
            "target_type": _target_type_for(path),
            "target_id":   None,
            "ip_address":  ip,
            "user_agent":  user_agent,
            "metadata":    {"path": path, "status": status_code},
        }).execute()
    except Exception as e:
        logger.debug(f"Audit log écriture: {e}")


def _target_type_for(path: str) -> Optional[str]:
    if path.startswith("/api/v1/identities"):
        return "identity"
    if path.startswith("/api/v1/kyc"):
        return "kyc_session"
    if path.startswith("/api/v1/access/zones"):
        return "zone"
    if path.startswith("/api/v1/access/policies"):
        return "access_policy"
    if path.startswith("/api/v1/access/check"):
        return "access_check"
    if path.startswith("/api/v1/clusters"):
        return "cluster"
    if path.startswith("/api/v1/auth"):
        return "auth_user"
    return None
