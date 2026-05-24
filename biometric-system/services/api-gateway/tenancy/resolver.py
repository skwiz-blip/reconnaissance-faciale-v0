"""
Résolution de tenant: API key → tenant ou X-Tenant-Id header.

Stratégie:
    1. Header `X-API-Key: bio_xxx` → lookup en DB (table tenant_api_keys)
    2. Header `X-Tenant-Id: <uuid|code>` → lookup direct (requiert JWT user)
    3. Subdomain (acme.api.your-domain.com) — voir middleware si activé

Cache Redis 60s pour éviter le round-trip Supabase à chaque requête.
"""
from __future__ import annotations

import hashlib
from typing import Optional

from fastapi import Request
from loguru import logger

from database import redis_cache
from database.supabase_client import get_supabase
from tenancy.context import TenantContext


TENANT_CACHE_PREFIX  = "bio:tenant:"
API_KEY_CACHE_PREFIX = "bio:apikey:"


def _hash_key(api_key: str) -> str:
    """Hash SHA-256 — on ne stocke jamais la clé en clair en DB."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


# ============================================================
# Lookups
# ============================================================

async def resolve_tenant_from_api_key(api_key: str) -> Optional[TenantContext]:
    if not api_key:
        return None
    key_hash = _hash_key(api_key)

    # 1. Cache
    import json
    cached = await redis_cache._get_raw(API_KEY_CACHE_PREFIX + key_hash)
    if cached:
        try:
            d = json.loads(cached)
            return TenantContext(**d)
        except Exception:
            pass

    # 2. Supabase
    sb = get_supabase()
    res = (
        sb.table("tenant_api_keys")
        .select("key_hash, is_active, tenants!inner(id, code, plan, quotas, is_active)")
        .eq("key_hash", key_hash)
        .eq("is_active", True)
        .execute()
    )
    if not res.data:
        return None
    row = res.data[0]
    t = row["tenants"]
    ctx = TenantContext(
        tenant_id=t["id"], code=t["code"], plan=t["plan"],
        quotas=t.get("quotas") or {}, is_active=t.get("is_active", True),
    )

    await redis_cache._set_raw(
        API_KEY_CACHE_PREFIX + key_hash,
        json.dumps(ctx.__dict__).encode("utf-8"),
        ttl=60,
    )
    # Mise à jour last_used_at en best-effort
    try:
        from datetime import datetime, timezone
        sb.table("tenant_api_keys").update(
            {"last_used_at": datetime.now(timezone.utc).isoformat()}
        ).eq("key_hash", key_hash).execute()
    except Exception:
        pass
    return ctx


async def resolve_tenant_by_code_or_id(token: str) -> Optional[TenantContext]:
    """Lookup direct par code (slug) ou UUID. Pas de vérif d'API key."""
    import json
    cached = await redis_cache._get_raw(TENANT_CACHE_PREFIX + token)
    if cached:
        try:
            return TenantContext(**json.loads(cached))
        except Exception:
            pass

    sb = get_supabase()
    # On tente UUID d'abord, puis code
    query = sb.table("tenants").select("id, code, plan, quotas, is_active")
    res = query.eq("id", token).execute() if _looks_like_uuid(token) else None
    if not res or not res.data:
        res = sb.table("tenants").select("id, code, plan, quotas, is_active").eq("code", token).execute()
    if not res.data:
        return None

    t = res.data[0]
    ctx = TenantContext(
        tenant_id=t["id"], code=t["code"], plan=t["plan"],
        quotas=t.get("quotas") or {}, is_active=t.get("is_active", True),
    )
    await redis_cache._set_raw(
        TENANT_CACHE_PREFIX + token,
        json.dumps(ctx.__dict__).encode("utf-8"),
        ttl=60,
    )
    return ctx


def _looks_like_uuid(s: str) -> bool:
    return len(s) == 36 and s.count("-") == 4


# ============================================================
# Dispatch principal
# ============================================================

async def resolve_tenant_from_request(request: Request) -> Optional[TenantContext]:
    # Priorité 1 : API key
    api_key = request.headers.get("x-api-key")
    if api_key:
        ctx = await resolve_tenant_from_api_key(api_key)
        if ctx:
            return ctx
        logger.debug(f"API key inconnue: {api_key[:8]}…")

    # Priorité 2 : header X-Tenant-Id (requiert un user JWT par ailleurs)
    tenant_token = request.headers.get("x-tenant-id")
    if tenant_token:
        return await resolve_tenant_by_code_or_id(tenant_token)

    return None
