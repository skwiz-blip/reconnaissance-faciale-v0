"""
Router voix — enrôlement + vérification + recherche 1:N.

Endpoints:
    POST /voice/enroll/{identity_id}     (upload audio)
    POST /voice/verify/{identity_id}     (1:1, retourne score)
    POST /voice/identify                 (1:N, retourne meilleurs candidats)
    POST /voice/fuse                     (fusion visage + voix → décision multimodale)
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../ai-core"))

import asyncio
import base64

import numpy as np
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from loguru import logger
from pydantic import BaseModel, Field

from auth.dependencies import require_user, AuthenticatedUser
from database.supabase_client import get_supabase
from tenancy.context import current_tenant


router = APIRouter(
    prefix="/api/v1/voice",
    tags=["Voix"],
    dependencies=[Depends(require_user)],
)


# ============================================================
# Schémas
# ============================================================

class FuseRequest(BaseModel):
    face_similarity:  float | None = Field(None, ge=0.0, le=1.0)
    voice_similarity: float | None = Field(None, ge=0.0, le=1.0)
    strategy:         str = Field("weighted_sum", pattern="^(weighted_sum|min_rule|max_rule|product_rule)$")
    threshold:        float = Field(0.62, ge=0.0, le=1.0)
    require_both:     bool = False


# ============================================================
# Endpoints
# ============================================================

@router.post("/enroll/{identity_id}")
async def enroll_voice(
    identity_id: str,
    file: UploadFile = File(..., description="Audio wav/mp3/flac >= 1s"),
    user: AuthenticatedUser = Depends(require_user),
):
    """Enrôle un échantillon vocal pour une identité existante."""
    audio_bytes = await file.read()
    ext = (file.filename or "wav").rsplit(".", 1)[-1].lower() if file.filename else "wav"

    from voice import get_voice_embedder
    embedder = get_voice_embedder()
    embedding = await asyncio.to_thread(embedder.embed_bytes, audio_bytes, ext)
    if embedding is None:
        raise HTTPException(400, "Audio invalide ou trop court (< 1s)")

    tenant = current_tenant()
    sb = get_supabase()
    res = sb.table("voice_embeddings").insert({
        "identity_id": identity_id,
        "tenant_id":   tenant.tenant_id if tenant else None,
        "embedding":   embedding.tolist(),
        "duration_seconds": None,
        "source":      "enrollment",
    }).execute()
    if not res.data:
        raise HTTPException(500, "Persist voice embedding échoué")

    return {"success": True, "voice_embedding_id": res.data[0]["id"], "dim": int(embedding.shape[0])}


@router.post("/verify/{identity_id}")
async def verify_voice(
    identity_id: str,
    file: UploadFile = File(...),
    threshold: float = Form(0.70),
):
    """Vérification 1:1 — l'audio correspond-il à cette identité ?"""
    audio_bytes = await file.read()
    ext = (file.filename or "wav").rsplit(".", 1)[-1].lower() if file.filename else "wav"

    from voice import get_voice_embedder
    embedder = get_voice_embedder()
    query = await asyncio.to_thread(embedder.embed_bytes, audio_bytes, ext)
    if query is None:
        raise HTTPException(400, "Audio invalide")

    sb = get_supabase()
    rows = (
        sb.table("voice_embeddings")
        .select("embedding").eq("identity_id", identity_id).execute()
    ).data or []
    if not rows:
        raise HTTPException(404, "Aucun voiceprint enrôlé pour cette identité")

    sims = []
    for r in rows:
        ref = np.array(r["embedding"], dtype=np.float32)
        ref = ref / (np.linalg.norm(ref) + 1e-9)
        sims.append(float(query @ ref))
    best = max(sims)
    return {
        "identity_id": identity_id,
        "similarity":  round(best, 4),
        "is_match":    best >= threshold,
        "threshold":   threshold,
        "n_references": len(rows),
    }


@router.post("/identify")
async def identify_voice(
    file: UploadFile = File(...),
    threshold: float = Form(0.70),
    limit: int = Form(5),
):
    """Recherche 1:N — qui parle ?"""
    audio_bytes = await file.read()
    ext = (file.filename or "wav").rsplit(".", 1)[-1].lower() if file.filename else "wav"

    from voice import get_voice_embedder
    embedder = get_voice_embedder()
    query = await asyncio.to_thread(embedder.embed_bytes, audio_bytes, ext)
    if query is None:
        raise HTTPException(400, "Audio invalide")

    tenant = current_tenant()
    sb = get_supabase()
    res = sb.rpc("search_voice", {
        "query_embedding": query.tolist(),
        "match_threshold": threshold,
        "match_count":     limit,
        "p_tenant_id":     tenant.tenant_id if tenant else None,
    }).execute()
    return {"matches": res.data or [], "threshold": threshold}


@router.post("/fuse")
async def fuse_modalities(payload: FuseRequest):
    """Fusion d'un score visage et d'un score voix (ne ré-exécute pas l'IA)."""
    from voice import fuse_face_voice
    r = fuse_face_voice(
        face_similarity=payload.face_similarity,
        voice_similarity=payload.voice_similarity,
        strategy=payload.strategy,
        threshold=payload.threshold,
        require_both=payload.require_both,
    )
    return {
        "decision":     r.decision,
        "fused_score":  r.fused_score,
        "face_score":   r.face_score,
        "voice_score":  r.voice_score,
        "strategy":     r.strategy,
        "threshold":    r.threshold,
        "reason":       r.reason,
    }
