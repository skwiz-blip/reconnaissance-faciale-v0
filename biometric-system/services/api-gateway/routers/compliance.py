"""
Router conformité RGPD — Art. 15 (accès), 17 (oubli), 20 (portabilité), 7 (consentement).

Endpoints réservés aux admins (sauf consultation par l'utilisateur lui-même
si l'auth est mappée à une identité — pas le cas dans cette version).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from loguru import logger
from pydantic import BaseModel, Field

from auth.dependencies import require_admin, AuthenticatedUser
from compliance.rgpd import (
    erase_identity, export_identity, export_to_json,
    record_consent, get_consent, withdraw_consent,
    anonymize_logs,
)
from compliance.retention import run_retention_pass
from database.supabase_client import get_supabase


router = APIRouter(
    prefix="/api/v1/compliance",
    tags=["RGPD / Conformité"],
    dependencies=[Depends(require_admin)],
)


# ============================================================
# Schémas
# ============================================================

class EraseRequest(BaseModel):
    reason: str = Field(default="user_request", max_length=240)


class ConsentRequest(BaseModel):
    identity_id:  str
    purpose:      str = Field(..., max_length=64)
    granted:      bool
    document_url: str | None = None


class AnonymizeRequest(BaseModel):
    older_than_days: int = Field(180, ge=7, le=3650)


# ============================================================
# Effacement (Art. 17)
# ============================================================

@router.post("/identities/{identity_id}/erase")
async def erase(identity_id: str, body: EraseRequest, user: AuthenticatedUser = Depends(require_admin)):
    """Droit à l'oubli — supprime toutes les données biométriques liées."""
    sb = get_supabase()
    # Enregistrer la demande (avant l'effacement pour conserver le lien)
    request_record = sb.table("erasure_requests").insert({
        "target_id":     identity_id,
        "requested_by":  user.user_id,
        "reason":        body.reason,
        "status":        "pending",
    }).execute()
    request_id = request_record.data[0]["id"] if request_record.data else None

    try:
        report = await erase_identity(identity_id, reason=body.reason)
    except Exception as e:
        if request_id:
            sb.table("erasure_requests").update({
                "status": "rejected", "reason": f"{body.reason} | err: {e}",
            }).eq("id", request_id).execute()
        raise HTTPException(500, f"Effacement échoué: {e}")

    if request_id:
        sb.table("erasure_requests").update({
            "status": "completed",
            "embeddings_deleted": report.embeddings_deleted,
            "events_anonymized":  report.events_anonymized,
            "completed_at":       report.completed_at.isoformat(),
        }).eq("id", request_id).execute()

    return {
        "request_id":  request_id,
        "identity_id": report.identity_id,
        "embeddings_deleted":       report.embeddings_deleted,
        "events_anonymized":        report.events_anonymized,
        "access_logs_anonymized":   report.access_logs_anonymized,
        "kyc_sessions_deleted":     report.kyc_sessions_deleted,
        "unknown_faces_unlinked":   report.unknown_faces_unlinked,
        "completed_at":             report.completed_at.isoformat(),
    }


# ============================================================
# Export (Art. 15 / 20)
# ============================================================

@router.get("/identities/{identity_id}/export")
async def export(identity_id: str):
    """
    Génère un dump JSON portable des données d'une identité.
    Streamed pour pouvoir gérer de gros volumes (events / logs).
    """
    try:
        pkg = await export_identity(identity_id)
    except ValueError as e:
        raise HTTPException(404, str(e))

    payload = export_to_json(pkg)
    return StreamingResponse(
        iter([payload]),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="export_{identity_id}.json"',
        },
    )


# ============================================================
# Consentement (Art. 7)
# ============================================================

@router.post("/consents")
async def record(body: ConsentRequest):
    res = await record_consent(
        identity_id=body.identity_id,
        purpose=body.purpose,
        granted=body.granted,
        document_url=body.document_url,
    )
    return {"recorded": True, "consent": res}


@router.get("/consents")
async def consent_status(identity_id: str = Query(...), purpose: str = Query(...)):
    c = await get_consent(identity_id, purpose)
    return {"identity_id": identity_id, "purpose": purpose, "consent": c}


@router.delete("/consents")
async def consent_withdraw(identity_id: str = Query(...), purpose: str = Query(...)):
    res = await withdraw_consent(identity_id, purpose)
    return {"withdrawn": True, "consent": res}


# ============================================================
# Rétention + anonymisation
# ============================================================

@router.post("/retention/run")
async def retention_run():
    results = await run_retention_pass()
    return {
        "ran_at": datetime.utcnow().isoformat() + "Z",
        "tables": [{"table": r.table, "deleted": r.deleted, "cutoff": r.cutoff} for r in results],
    }


@router.post("/anonymize-logs")
async def anonymize(body: AnonymizeRequest):
    return await anonymize_logs(body.older_than_days)


# ============================================================
# Vue compliance par identité
# ============================================================

@router.get("/status")
async def status_view(limit: int = Query(100, ge=1, le=500)):
    sb = get_supabase()
    res = (
        sb.table("identity_compliance_view")
        .select("*")
        .limit(limit)
        .execute()
    )
    return res.data or []
