"""
Router webhooks — CRUD endpoints + historique + replay.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, HttpUrl

from auth.dependencies import require_user, require_admin, AuthenticatedUser
from database.supabase_client import get_supabase
from tenancy.context import require_tenant
from webhooks.dispatcher import generate_secret, dispatch_event, EVENT_TYPES


router = APIRouter(
    prefix="/api/v1/webhooks",
    tags=["Webhooks"],
    dependencies=[Depends(require_user)],
)


# ============================================================
# Schémas
# ============================================================

class WebhookCreate(BaseModel):
    url:         HttpUrl
    events:      list[str] = Field(..., min_length=1)
    description: str | None = None


class WebhookCreated(BaseModel):
    id:          str
    url:         str
    events:      list[str]
    secret:      str           # affiché UNE SEULE FOIS


# ============================================================
# Endpoints
# ============================================================

@router.get("/events")
async def list_event_types():
    return {"event_types": list(EVENT_TYPES)}


@router.post("", response_model=WebhookCreated, status_code=201)
async def create_webhook(payload: WebhookCreate):
    tenant = require_tenant()
    # Validation des events
    invalid = [e for e in payload.events if e not in EVENT_TYPES]
    if invalid:
        raise HTTPException(400, f"Events inconnus: {invalid}")

    secret = generate_secret()
    sb = get_supabase()
    res = sb.table("webhooks").insert({
        "tenant_id":   tenant.tenant_id,
        "url":         str(payload.url),
        "secret":      secret,
        "events":      payload.events,
        "description": payload.description,
    }).execute()
    if not res.data:
        raise HTTPException(500, "Création webhook échouée")
    rec = res.data[0]
    return WebhookCreated(
        id=rec["id"], url=rec["url"], events=rec["events"], secret=secret,
    )


@router.get("")
async def list_webhooks():
    tenant = require_tenant()
    sb = get_supabase()
    res = (
        sb.table("webhooks")
        .select("id, url, events, is_active, description, created_at")
        .eq("tenant_id", tenant.tenant_id)
        .order("created_at", desc=True).execute()
    )
    return res.data or []


@router.delete("/{webhook_id}", status_code=204)
async def delete_webhook(webhook_id: str):
    tenant = require_tenant()
    sb = get_supabase()
    sb.table("webhooks").delete().eq("id", webhook_id).eq("tenant_id", tenant.tenant_id).execute()


@router.get("/{webhook_id}/deliveries")
async def list_deliveries(webhook_id: str, limit: int = Query(50, ge=1, le=200)):
    tenant = require_tenant()
    sb = get_supabase()
    # Sécurité: vérifier que le webhook appartient au tenant
    w = sb.table("webhooks").select("id").eq("id", webhook_id).eq("tenant_id", tenant.tenant_id).execute()
    if not w.data:
        raise HTTPException(404, "Webhook introuvable")
    res = (
        sb.table("webhook_deliveries")
        .select("id, event_type, status, attempts, http_status, error, completed_at, created_at")
        .eq("webhook_id", webhook_id)
        .order("created_at", desc=True).limit(limit).execute()
    )
    return res.data or []


@router.post("/test")
async def test_dispatch(event_type: str = Query("recognition.matched")):
    """Envoie un payload de test à tous les webhooks abonnés."""
    tenant = require_tenant()
    n = await dispatch_event(event_type, {"test": True, "ts": "from /webhooks/test"}, tenant_id=tenant.tenant_id)
    return {"dispatched_to": n}
