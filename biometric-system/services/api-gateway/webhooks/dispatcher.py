"""
Webhooks — dispatch HTTP signé HMAC vers les endpoints des tenants.

Pattern Stripe:
    - Header `X-Bio-Signature: t=<ts>,v1=<hmac_sha256(ts.body)>`
    - Le partenaire vérifie le HMAC avec son `webhook_secret`
    - Replay protection: timestamp + tolérance 5 minutes

Retry:
    - 3 tentatives avec backoff exponentiel (1s, 4s, 16s)
    - Si échec final, statut "failed" + payload conservé pour rejouer manuellement

Tâche Celery `tasks.dispatch_webhook` pour ne pas bloquer la requête API.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Optional

import httpx
from loguru import logger

from database.supabase_client import get_supabase


# ============================================================
# Events
# ============================================================

EVENT_TYPES = (
    "recognition.matched",
    "recognition.unknown",
    "recognition.spoof_detected",
    "access.granted",
    "access.denied",
    "access.alert",
    "kyc.approved",
    "kyc.rejected",
    "kyc.review",
    "identity.created",
    "identity.deleted",
    "rgpd.erased",
)


@dataclass(slots=True)
class WebhookEvent:
    type:       str
    tenant_id:  Optional[str]
    data:       dict
    created_at: float


# ============================================================
# Signature HMAC (style Stripe)
# ============================================================

def sign_payload(secret: str, payload: str, timestamp: Optional[int] = None) -> str:
    ts = timestamp or int(time.time())
    msg = f"{ts}.{payload}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def verify_signature(secret: str, payload: str, header_value: str,
                     tolerance_seconds: int = 300) -> bool:
    try:
        parts = dict(p.split("=", 1) for p in header_value.split(","))
        ts = int(parts["t"])
        if abs(time.time() - ts) > tolerance_seconds:
            return False
        msg = f"{ts}.{payload}".encode("utf-8")
        expected = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, parts["v1"])
    except Exception:
        return False


# ============================================================
# Dispatch
# ============================================================

async def dispatch_event(
    event_type: str,
    data: dict,
    tenant_id: Optional[str] = None,
) -> int:
    """
    Énumère les webhooks abonnés et déclenche la livraison async.
    Retourne le nombre de webhooks ciblés.
    """
    if event_type not in EVENT_TYPES:
        logger.warning(f"Type d'événement inconnu: {event_type}")
        return 0

    sb = get_supabase()
    query = (
        sb.table("webhooks")
        .select("id, url, secret, events, is_active")
        .eq("is_active", True)
    )
    if tenant_id:
        query = query.eq("tenant_id", tenant_id)
    rows = query.execute().data or []

    targets = [w for w in rows if event_type in (w.get("events") or [])]
    if not targets:
        return 0

    payload = json.dumps({
        "type": event_type, "data": data,
        "created_at": int(time.time()), "tenant_id": tenant_id,
    }, default=str)

    # Lance la livraison en arrière-plan (asyncio tasks)
    for w in targets:
        asyncio.create_task(_deliver_one(w, event_type, payload))
    return len(targets)


async def _deliver_one(webhook: dict, event_type: str, payload: str) -> None:
    delivery_id: Optional[str] = None
    sb = get_supabase()
    try:
        rec = sb.table("webhook_deliveries").insert({
            "webhook_id":   webhook["id"],
            "event_type":   event_type,
            "payload":      payload,
            "status":       "pending",
            "attempts":     0,
        }).execute()
        delivery_id = rec.data[0]["id"] if rec.data else None
    except Exception as e:
        logger.warning(f"Persist webhook_delivery: {e}")

    attempts = 0
    last_status: Optional[int] = None
    last_error:  Optional[str] = None

    for delay in (0, 4, 16):
        if delay:
            await asyncio.sleep(delay)
        attempts += 1
        try:
            sig = sign_payload(webhook["secret"], payload)
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(
                    webhook["url"], content=payload,
                    headers={
                        "Content-Type":     "application/json",
                        "X-Bio-Signature":  sig,
                        "X-Bio-Event":      event_type,
                        "X-Bio-Delivery":   delivery_id or "",
                        "User-Agent":       "biometric-webhook/1.0",
                    },
                )
            last_status = r.status_code
            if 200 <= r.status_code < 300:
                _update_delivery(delivery_id, "delivered", attempts, last_status, None)
                return
            last_error = f"HTTP {r.status_code}: {r.text[:240]}"
        except Exception as e:
            last_error = str(e)[:240]

    _update_delivery(delivery_id, "failed", attempts, last_status, last_error)
    logger.warning(f"Webhook {webhook['url']} failed after {attempts}: {last_error}")


def _update_delivery(
    delivery_id: Optional[str], status: str, attempts: int,
    http_status: Optional[int], error: Optional[str],
) -> None:
    if not delivery_id:
        return
    try:
        get_supabase().table("webhook_deliveries").update({
            "status":       status,
            "attempts":     attempts,
            "http_status":  http_status,
            "error":        error,
            "completed_at": "now()",
        }).eq("id", delivery_id).execute()
    except Exception as e:
        logger.debug(f"Update webhook_delivery: {e}")


def generate_secret() -> str:
    """Génère un webhook secret 32 bytes (à donner au partenaire une seule fois)."""
    return "whsec_" + secrets.token_urlsafe(32)
