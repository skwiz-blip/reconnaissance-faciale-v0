"""
Router affect — analyse émotionnelle + stress sur image ou flux.

Endpoints:
    POST /affect/emotion   (image base64 → top emotion + distribution)
    POST /affect/stress    (séquence de frames → stress score)
    GET  /affect/timeline  (séries temporelles par identité)
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../ai-core"))

import base64

import cv2
import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from auth.dependencies import require_user, AuthenticatedUser
from database.supabase_client import get_supabase
from tenancy.context import current_tenant


router = APIRouter(
    prefix="/api/v1/affect",
    tags=["Affect (émotions / stress)"],
    dependencies=[Depends(require_user)],
)


# ============================================================
# Schémas
# ============================================================

class EmotionRequest(BaseModel):
    image_base64: str
    identity_id:  str | None = None
    event_id:     str | None = None


class FrameSignal(BaseModel):
    blink:     bool = False
    yaw:       float | None = None
    emotion:   str = "neutral"
    asymmetry: float = 0.0


class StressRequest(BaseModel):
    frames: list[FrameSignal] = Field(..., min_length=5)
    identity_id: str | None = None


# ============================================================
# Helpers
# ============================================================

def _decode_b64_image(s: str) -> np.ndarray:
    if "," in s:
        s = s.split(",", 1)[1]
    arr = np.frombuffer(base64.b64decode(s), np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "Image non décodable")
    return img


# ============================================================
# Endpoints
# ============================================================

@router.post("/emotion")
async def detect_emotion(payload: EmotionRequest):
    img = _decode_b64_image(payload.image_base64)
    from detector import get_detector
    from affect import analyze_emotion

    faces = get_detector().detect(img)
    if not faces:
        raise HTTPException(404, "Aucun visage détecté")
    face = faces[0]
    result = analyze_emotion(face.face_img, face.landmarks)

    # Persistance optionnelle
    if payload.event_id or payload.identity_id:
        tenant = current_tenant()
        try:
            get_supabase().table("affect_signals").insert({
                "event_id":             payload.event_id,
                "identity_id":          payload.identity_id,
                "tenant_id":            tenant.tenant_id if tenant else None,
                "top_emotion":          result.top_emotion,
                "emotion_confidence":   result.confidence,
                "emotion_distribution": result.distribution,
            }).execute()
        except Exception:
            pass

    return {
        "top_emotion": result.top_emotion,
        "confidence":  result.confidence,
        "distribution": result.distribution,
        "source":      result.source,
    }


@router.post("/stress")
async def detect_stress(payload: StressRequest):
    """
    Analyse stress sur une séquence de frames déjà annotées
    (le client transmet blink/yaw/emotion/asymmetry par frame).
    """
    from affect import analyze_stress
    result = analyze_stress([f.model_dump() for f in payload.frames])

    if payload.identity_id:
        tenant = current_tenant()
        try:
            get_supabase().table("affect_signals").insert({
                "identity_id":   payload.identity_id,
                "tenant_id":     tenant.tenant_id if tenant else None,
                "stress_level":  result.level.value,
                "stress_score":  result.score,
                "metadata": {
                    "blink_rate_per_min": result.blink_rate_per_min,
                    "head_yaw_variance":  result.head_yaw_variance,
                    "negative_emotion_ratio": result.negative_emotion_ratio,
                    "n_frames":           result.n_frames,
                },
            }).execute()
        except Exception:
            pass

    return {
        "level":  result.level.value,
        "score":  result.score,
        "blink_rate_per_min":      result.blink_rate_per_min,
        "head_yaw_variance":       result.head_yaw_variance,
        "negative_emotion_ratio":  result.negative_emotion_ratio,
        "asymmetry":               result.asymmetry,
        "n_frames":                result.n_frames,
    }


@router.get("/timeline/{identity_id}")
async def affect_timeline(identity_id: str, days: int = Query(7, ge=1, le=90)):
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    sb = get_supabase()
    res = (
        sb.table("affect_signals").select("*")
        .eq("identity_id", identity_id)
        .gte("created_at", cutoff)
        .order("created_at", desc=False)
        .execute()
    )
    return res.data or []
