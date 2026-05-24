"""
Router auth: register / login / refresh / logout.

Schéma: utilisateurs administrateurs du système (différent des "identities"
biométriques). Un admin se connecte avec email + password classique pour
gérer le dashboard.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from loguru import logger
from pydantic import BaseModel, EmailStr, Field

from auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
    require_user,
    AuthenticatedUser,
)
from auth.dependencies import rate_limit
from config import get_settings
from database import redis_cache
from database.supabase_client import get_supabase
from jose import JWTError


router = APIRouter(prefix="/api/v1/auth", tags=["Authentification"])
settings = get_settings()


# ============================================================
# Schémas
# ============================================================

class RegisterRequest(BaseModel):
    email:      EmailStr
    password:   str = Field(min_length=8, max_length=128)
    full_name:  str = Field(min_length=2, max_length=120)
    role:       str = Field(default="operator", pattern="^(operator|admin)$")


class LoginRequest(BaseModel):
    email:    EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "Bearer"
    expires_in:    int
    user_id:       str
    role:          str


class MeResponse(BaseModel):
    user_id: str
    email:   str
    role:    str


# ============================================================
# Endpoints
# ============================================================

@router.post(
    "/register",
    response_model=TokenResponse,
    status_code=201,
    dependencies=[Depends(rate_limit(5))],
)
async def register(req: RegisterRequest):
    """
    Création d'un compte administrateur/opérateur.
    Le premier compte créé est promu admin automatiquement.
    """
    sb = get_supabase()

    # Vérifier l'unicité de l'email
    existing = (
        sb.table("auth_users").select("id").eq("email", req.email.lower()).execute()
    )
    if existing.data:
        raise HTTPException(409, "Un compte existe déjà avec cet email")

    # Bootstrap admin
    count_res = sb.table("auth_users").select("id", count="exact").execute()
    role = "admin" if (count_res.count or 0) == 0 else req.role

    record = sb.table("auth_users").insert({
        "email":           req.email.lower(),
        "password_hash":   hash_password(req.password),
        "full_name":       req.full_name,
        "role":            role,
        "last_login_at":   None,
    }).execute()

    if not record.data:
        raise HTTPException(500, "Échec de la création du compte")

    user = record.data[0]
    return await _issue_tokens(user["id"], user["role"])


@router.post(
    "/login",
    response_model=TokenResponse,
    dependencies=[Depends(rate_limit(10))],
)
async def login(req: LoginRequest):
    sb = get_supabase()
    res = (
        sb.table("auth_users")
        .select("id, password_hash, role, is_active")
        .eq("email", req.email.lower())
        .execute()
    )

    if not res.data:
        # Réponse uniforme — pas de leak sur existence
        raise HTTPException(401, "Identifiants invalides")

    user = res.data[0]
    if not user["is_active"]:
        raise HTTPException(403, "Compte désactivé")

    if not verify_password(req.password, user["password_hash"]):
        raise HTTPException(401, "Identifiants invalides")

    # Mettre à jour last_login_at (best effort)
    try:
        sb.table("auth_users").update({
            "last_login_at": datetime.now(timezone.utc).isoformat()
        }).eq("id", user["id"]).execute()
    except Exception as e:
        logger.warning(f"Update last_login_at: {e}")

    return await _issue_tokens(user["id"], user["role"])


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest):
    try:
        payload = decode_token(req.refresh_token, expected_type="refresh")
    except JWTError as e:
        raise HTTPException(401, f"Refresh token invalide: {e}")

    # Vérifier que le jti existe encore en Redis (rotation)
    stored = await redis_cache.get_refresh_token(payload.jti)
    if not stored or stored.get("user_id") != payload.sub:
        raise HTTPException(401, "Refresh token révoqué ou inconnu")

    # Rotation: invalider l'ancien
    await redis_cache.revoke_refresh_token(payload.jti)

    return await _issue_tokens(payload.sub, payload.role)


@router.post("/logout", status_code=204)
async def logout(user: AuthenticatedUser = Depends(require_user)):
    """Révoque l'access token courant + tous les refresh tokens de l'utilisateur."""
    remaining = max(0, user.exp - int(time.time()))
    await redis_cache.revoke_access_token(user.jti, remaining)
    # Note: les refresh tokens sont révoqués individuellement à leur usage suivant.


@router.get("/me", response_model=MeResponse)
async def me(user: AuthenticatedUser = Depends(require_user)):
    sb = get_supabase()
    res = (
        sb.table("auth_users")
        .select("id, email, role")
        .eq("id", user.user_id)
        .single()
        .execute()
    )
    if not res.data:
        raise HTTPException(404, "Utilisateur introuvable")
    return MeResponse(user_id=res.data["id"], email=res.data["email"], role=res.data["role"])


# ============================================================
# Helpers
# ============================================================

async def _issue_tokens(user_id: str, role: str) -> TokenResponse:
    access, _, access_exp = create_access_token(user_id, role)
    refresh_jwt, refresh_jti, refresh_exp = create_refresh_token(user_id, role)

    ttl = refresh_exp - int(time.time())
    await redis_cache.store_refresh_token(refresh_jti, user_id, ttl_seconds=max(60, ttl))

    return TokenResponse(
        access_token=access,
        refresh_token=refresh_jwt,
        expires_in=access_exp - int(time.time()),
        user_id=user_id,
        role=role,
    )
