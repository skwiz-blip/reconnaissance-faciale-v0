"""
Router tenants — CRUD organisations SaaS + API keys.
Réservé aux admins de la plateforme.
"""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field

from auth.dependencies import require_admin, AuthenticatedUser
from database.supabase_client import get_supabase
from tenancy.resolver import _hash_key


router = APIRouter(
    prefix="/api/v1/tenants",
    tags=["SaaS / Tenants"],
    dependencies=[Depends(require_admin)],
)


# ============================================================
# Schémas
# ============================================================

class TenantCreate(BaseModel):
    code:          str = Field(..., min_length=2, max_length=64, pattern=r"^[a-z0-9_\-]+$")
    name:          str = Field(..., min_length=2, max_length=120)
    plan:          str = Field(default="free", pattern="^(free|pro|enterprise)$")
    contact_email: EmailStr | None = None
    quotas:        dict | None = None


class TenantUpdate(BaseModel):
    name:          str | None = None
    plan:          str | None = Field(None, pattern="^(free|pro|enterprise)$")
    is_active:     bool | None = None
    quotas:        dict | None = None


class ApiKeyCreate(BaseModel):
    name:   str = Field(..., min_length=2, max_length=120)
    scopes: list[str] = Field(default_factory=lambda: ["recognize", "access"])


class ApiKeyCreated(BaseModel):
    id:         str
    name:       str
    api_key:    str            # affiché UNE SEULE FOIS
    key_prefix: str
    scopes:     list[str]


# ============================================================
# Tenants CRUD
# ============================================================

@router.post("", status_code=201)
async def create_tenant(payload: TenantCreate):
    sb = get_supabase()
    res = sb.table("tenants").insert(payload.model_dump(exclude_none=True)).execute()
    if not res.data:
        raise HTTPException(500, "Création tenant échouée")
    return res.data[0]


@router.get("")
async def list_tenants(active_only: bool = Query(True)):
    sb = get_supabase()
    q = sb.table("tenant_overview").select("*").order("identities_count", desc=True)
    if active_only:
        q = q.eq("is_active", True)
    return q.execute().data or []


@router.get("/{tenant_id}")
async def get_tenant(tenant_id: str):
    sb = get_supabase()
    res = sb.table("tenants").select("*").eq("id", tenant_id).single().execute()
    if not res.data:
        raise HTTPException(404, "Tenant introuvable")
    return res.data


@router.patch("/{tenant_id}")
async def update_tenant(tenant_id: str, payload: TenantUpdate):
    sb = get_supabase()
    update = payload.model_dump(exclude_none=True)
    if not update:
        raise HTTPException(400, "Rien à mettre à jour")
    res = sb.table("tenants").update(update).eq("id", tenant_id).execute()
    if not res.data:
        raise HTTPException(404, "Tenant introuvable")
    return res.data[0]


@router.delete("/{tenant_id}", status_code=204)
async def delete_tenant(tenant_id: str):
    sb = get_supabase()
    sb.table("tenants").delete().eq("id", tenant_id).execute()


# ============================================================
# API keys
# ============================================================

@router.post("/{tenant_id}/api-keys", response_model=ApiKeyCreated, status_code=201)
async def create_api_key(tenant_id: str, payload: ApiKeyCreate):
    raw_key = "bio_" + secrets.token_urlsafe(32)
    sb = get_supabase()
    res = sb.table("tenant_api_keys").insert({
        "tenant_id":  tenant_id,
        "name":       payload.name,
        "key_hash":   _hash_key(raw_key),
        "key_prefix": raw_key[:12],
        "scopes":     payload.scopes,
    }).execute()
    if not res.data:
        raise HTTPException(500, "Création clé échouée")
    rec = res.data[0]
    return ApiKeyCreated(
        id=rec["id"], name=rec["name"], api_key=raw_key,
        key_prefix=rec["key_prefix"], scopes=rec["scopes"],
    )


@router.get("/{tenant_id}/api-keys")
async def list_api_keys(tenant_id: str):
    sb = get_supabase()
    res = (
        sb.table("tenant_api_keys")
        .select("id, name, key_prefix, scopes, is_active, last_used_at, expires_at, created_at")
        .eq("tenant_id", tenant_id).order("created_at", desc=True).execute()
    )
    return res.data or []


@router.delete("/{tenant_id}/api-keys/{key_id}", status_code=204)
async def revoke_api_key(tenant_id: str, key_id: str):
    sb = get_supabase()
    sb.table("tenant_api_keys").update({"is_active": False}).eq("id", key_id).eq("tenant_id", tenant_id).execute()


@router.get("/{tenant_id}/usage")
async def tenant_usage(tenant_id: str, days: int = Query(30, ge=1, le=365)):
    sb = get_supabase()
    res = (
        sb.table("tenant_usage_daily").select("*")
        .eq("tenant_id", tenant_id)
        .order("day", desc=True).limit(days).execute()
    )
    return res.data or []
