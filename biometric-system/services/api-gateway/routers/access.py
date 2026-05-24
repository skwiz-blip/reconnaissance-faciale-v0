"""
Router contrôle d'accès — vérification temps réel + CRUD zones/politiques.

Endpoints clés:
    POST /access/check         → décide granted/denied/alert sur une image
    CRUD /access/zones         → gestion zones (admin)
    CRUD /access/policies      → gestion politiques (admin)
    GET  /access/logs          → historique des décisions
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../ai-core"))

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger

from auth.dependencies import require_user, require_admin, AuthenticatedUser
from access.policy_engine import (
    evaluate_access_for_identity, invalidate_zone_cache,
)
from database.supabase_client import (
    get_supabase, log_access, log_recognition_event,
)
from models.schemas_v3 import (
    AccessCheckRequest, AccessCheckResponse,
    ZoneCreate, ZoneUpdate, ZoneResponse,
    AccessPolicyCreate, AccessPolicyResponse,
)


router = APIRouter(
    prefix="/api/v1/access",
    tags=["Contrôle d'accès"],
    dependencies=[Depends(require_user)],
)


# ============================================================
# Vérification temps réel
# ============================================================

@router.post("/check", response_model=AccessCheckResponse)
async def check_access(req: AccessCheckRequest):
    """
    Pipeline complet: image → reconnaissance → décision d'accès → log.
    Appelé par les caméras de porte / kiosques d'entrée.
    """
    from pipeline import get_pipeline
    pipeline = get_pipeline()
    t0 = time.perf_counter()

    result = await pipeline.process_base64(
        req.image_base64, check_liveness=req.check_liveness
    )

    identity_id = result.matches[0].identity_id if result.matches else None
    identity_name = result.matches[0].full_name if result.matches else None
    similarity = result.matches[0].similarity if result.matches else None

    # Évaluation policy engine
    access = await evaluate_access_for_identity(
        identity_id=identity_id,
        zone_code=req.zone_code,
        access_point=req.access_point,
        similarity=similarity,
        liveness_passed=result.is_live,
        liveness_score=result.liveness_score,
        camera_id=req.camera_id,
    )

    # Log recognition_event + access_log
    event_id, access_log_id = None, None
    try:
        event_type = "recognized" if identity_id else ("spoof_detected" if not result.is_live else "unknown")
        event = await log_recognition_event({
            "event_type":     event_type,
            "confidence":     similarity,
            "liveness_score": result.liveness_score,
            "camera_id":      req.camera_id,
            "location":       req.zone_code,
            "identity_id":    identity_id,
        })
        event_id = event["id"]
        access_log = await log_access(
            identity_id=identity_id or "00000000-0000-0000-0000-000000000000",
            event_id=event_id,
            access_point=req.access_point,
            decision=access.decision.value,
            reason=access.reason,
            zone=req.zone_code,
        )
        access_log_id = access_log["id"]
    except Exception as e:
        logger.warning(f"Persist access logs: {e}")

    return AccessCheckResponse(
        decision=access.decision.value,
        reason=access.reason,
        identity_id=identity_id,
        identity_name=identity_name,
        similarity=similarity,
        liveness_score=result.liveness_score,
        matched_policy=access.matched_policy,
        zone=req.zone_code,
        access_point=req.access_point,
        event_id=event_id,
        access_log_id=access_log_id,
        processing_ms=round((time.perf_counter() - t0) * 1000, 1),
    )


# ============================================================
# Zones (admin)
# ============================================================

@router.post(
    "/zones",
    response_model=ZoneResponse,
    status_code=201,
    dependencies=[Depends(require_admin)],
)
async def create_zone(payload: ZoneCreate):
    sb = get_supabase()
    res = sb.table("zones").insert(payload.model_dump(mode="json", exclude_none=True)).execute()
    if not res.data:
        raise HTTPException(500, "Création zone échouée")
    zone = res.data[0]
    await invalidate_zone_cache(zone["code"], zone["id"])
    return ZoneResponse(**zone)


@router.get("/zones", response_model=list[ZoneResponse])
async def list_zones(active_only: bool = Query(True)):
    sb = get_supabase()
    q = sb.table("zones").select("*").order("created_at", desc=False)
    if active_only:
        q = q.eq("is_active", True)
    return [ZoneResponse(**z) for z in q.execute().data or []]


@router.patch(
    "/zones/{zone_id}",
    response_model=ZoneResponse,
    dependencies=[Depends(require_admin)],
)
async def update_zone(zone_id: str, payload: ZoneUpdate):
    sb = get_supabase()
    update = payload.model_dump(mode="json", exclude_none=True)
    if not update:
        raise HTTPException(400, "Rien à mettre à jour")
    res = sb.table("zones").update(update).eq("id", zone_id).execute()
    if not res.data:
        raise HTTPException(404, "Zone introuvable")
    zone = res.data[0]
    await invalidate_zone_cache(zone["code"], zone["id"])
    return ZoneResponse(**zone)


@router.delete("/zones/{zone_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_zone(zone_id: str):
    sb = get_supabase()
    res = sb.table("zones").select("code").eq("id", zone_id).execute()
    if not res.data:
        raise HTTPException(404, "Zone introuvable")
    code = res.data[0]["code"]
    sb.table("zones").delete().eq("id", zone_id).execute()
    await invalidate_zone_cache(code, zone_id)


# ============================================================
# Policies (admin)
# ============================================================

@router.post(
    "/policies",
    response_model=AccessPolicyResponse,
    status_code=201,
    dependencies=[Depends(require_admin)],
)
async def create_policy(payload: AccessPolicyCreate):
    sb = get_supabase()
    data = payload.model_dump(mode="json", exclude_none=True)
    res = sb.table("access_policies").insert(data).execute()
    if not res.data:
        raise HTTPException(500, "Création politique échouée")
    policy = res.data[0]
    # Invalidate cache des politiques de la zone
    zone_res = sb.table("zones").select("code").eq("id", policy["zone_id"]).execute()
    if zone_res.data:
        await invalidate_zone_cache(zone_res.data[0]["code"], policy["zone_id"])
    return AccessPolicyResponse(**policy)


@router.get("/policies", response_model=list[AccessPolicyResponse])
async def list_policies(zone_id: str | None = None):
    sb = get_supabase()
    q = sb.table("access_policies").select("*").order("priority", desc=True)
    if zone_id:
        q = q.eq("zone_id", zone_id)
    return [AccessPolicyResponse(**p) for p in q.execute().data or []]


@router.delete(
    "/policies/{policy_id}",
    status_code=204,
    dependencies=[Depends(require_admin)],
)
async def delete_policy(policy_id: str):
    sb = get_supabase()
    res = sb.table("access_policies").select("zone_id").eq("id", policy_id).execute()
    if not res.data:
        raise HTTPException(404, "Politique introuvable")
    zone_id = res.data[0]["zone_id"]
    sb.table("access_policies").delete().eq("id", policy_id).execute()
    zone_res = sb.table("zones").select("code").eq("id", zone_id).execute()
    if zone_res.data:
        await invalidate_zone_cache(zone_res.data[0]["code"], zone_id)


# ============================================================
# Logs
# ============================================================

@router.get("/logs")
async def list_access_logs(
    limit: int = Query(50, ge=1, le=500),
    decision: str | None = Query(None, pattern="^(granted|denied|alert)$"),
    zone: str | None = None,
):
    sb = get_supabase()
    q = sb.table("access_summary").select("*").order("created_at", desc=True).limit(limit)
    if decision:
        q = q.eq("decision", decision)
    if zone:
        q = q.eq("zone", zone)
    return q.execute().data or []
