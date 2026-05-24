"""
Contexte tenant via ContextVar — thread/coroutine-safe.

Lecture: `current_tenant()` n'importe où dans le code des routers/services.
Le middleware tenancy.middleware le pose au début de chaque requête.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, status


@dataclass(slots=True, frozen=True)
class TenantContext:
    tenant_id:   str
    code:        str               # slug humain ex: "acme-corp"
    plan:        str               # "free" | "pro" | "enterprise"
    quotas:      dict              # ex: {"recognitions_per_day": 10_000}
    is_active:   bool = True


_var: ContextVar[Optional[TenantContext]] = ContextVar("biometric_tenant", default=None)


def current_tenant() -> Optional[TenantContext]:
    return _var.get()


def set_current_tenant(ctx: Optional[TenantContext]) -> None:
    _var.set(ctx)


def require_tenant() -> TenantContext:
    """Lève 400 si pas de tenant résolu. Pour endpoints multi-tenant obligatoires."""
    ctx = _var.get()
    if ctx is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tenant manquant — fournir X-Tenant-Id ou X-API-Key",
        )
    if not ctx.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Tenant {ctx.code} désactivé",
        )
    return ctx
