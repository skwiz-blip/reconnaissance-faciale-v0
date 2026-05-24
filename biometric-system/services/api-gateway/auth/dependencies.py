"""
Dépendances FastAPI pour l'authentification et le contrôle de rôles.

Usage:
    @router.get("/admin/...")
    async def admin_route(user: AuthenticatedUser = Depends(require_admin)):
        ...
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from fastapi import Depends, HTTPException, Request, WebSocket, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError

from auth.jwt_handler import decode_token, TokenPayload
from database import redis_cache


bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(slots=True)
class AuthenticatedUser:
    user_id: str
    role: str
    jti: str
    exp: int


# ============================================================
# HTTP dependency
# ============================================================

async def require_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> AuthenticatedUser:
    """Exige un access token JWT valide. Retourne l'utilisateur authentifié."""
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer token manquant",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await _validate_token(credentials.credentials)


def require_role(*allowed_roles: str) -> Callable:
    """
    Factory: dependency exigeant un des rôles donnés.
    Exemple: Depends(require_role("admin", "supervisor"))
    """
    async def _checker(user: AuthenticatedUser = Depends(require_user)) -> AuthenticatedUser:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Rôle requis: {' ou '.join(allowed_roles)}",
            )
        return user
    return _checker


require_admin = require_role("admin")


# ============================================================
# WebSocket dependency
# ============================================================

async def authenticate_websocket(websocket: WebSocket) -> AuthenticatedUser | None:
    """
    Authentifie une connexion WebSocket via query param `?token=...`
    ou header `Authorization: Bearer ...`.

    En cas d'échec: ferme la WS avec code 1008 (policy violation) et retourne None.
    """
    token: str | None = None

    auth_header = websocket.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()

    if not token:
        token = websocket.query_params.get("token")

    if not token:
        await websocket.close(code=1008, reason="Token manquant")
        return None

    try:
        return await _validate_token(token)
    except HTTPException as e:
        await websocket.close(code=1008, reason=e.detail)
        return None


# ============================================================
# Core validation
# ============================================================

async def _validate_token(token: str) -> AuthenticatedUser:
    try:
        payload: TokenPayload = decode_token(token, expected_type="access")
    except JWTError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token invalide: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if payload.exp < int(time.time()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expiré",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if await redis_cache.is_access_revoked(payload.jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token révoqué",
        )

    return AuthenticatedUser(
        user_id=payload.sub,
        role=payload.role,
        jti=payload.jti,
        exp=payload.exp,
    )


# ============================================================
# Rate limit dependency (par IP + endpoint)
# ============================================================

def rate_limit(limit_per_minute: int) -> Callable:
    async def _checker(request: Request) -> None:
        client_ip = request.client.host if request.client else "unknown"
        key = f"{client_ip}:{request.url.path}"
        ok, count = await redis_cache.rate_limit_check(
            key, limit_per_minute, window_seconds=60
        )
        if not ok:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Limite atteinte ({limit_per_minute}/min)",
                headers={"Retry-After": "60"},
            )
    return _checker
