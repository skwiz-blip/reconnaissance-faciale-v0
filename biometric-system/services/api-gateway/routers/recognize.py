"""
Router: Reconnaissance faciale
POST /api/v1/recognize — base64
POST /api/v1/recognize/upload — multipart
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../ai-core"))

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from loguru import logger

from models.schemas import (
    RecognizeRequest, RecognizeResponse, MatchInfo
)
from database.supabase_client import log_recognition_event, upload_image
from database import redis_cache
from auth.dependencies import require_user, rate_limit, AuthenticatedUser
from config import get_settings

settings = get_settings()

router = APIRouter(
    prefix="/api/v1/recognize",
    tags=["Reconnaissance"],
    dependencies=[
        Depends(require_user),
        Depends(rate_limit(settings.rate_limit_per_minute)),
    ],
)


@router.post("", response_model=RecognizeResponse)
async def recognize_base64(req: RecognizeRequest):
    """
    Reconnaissance faciale depuis une image base64.
    Retourne l'identité reconnue, score de confiance et résultat anti-spoof.
    """
    from pipeline import get_pipeline
    pipeline = get_pipeline()

    result = await pipeline.process_base64(
        req.image_base64,
        check_liveness=req.check_liveness
    )

    # Déterminer le type d'événement
    if not result.success:
        event_type = "rejected"
    elif not result.is_live:
        event_type = "spoof_detected"
    elif result.matches:
        event_type = "recognized"
    else:
        event_type = "unknown"

    # Logger l'événement dans Supabase
    event_id = None
    try:
        event_data = {
            "event_type":     event_type,
            "confidence":     result.matches[0].similarity if result.matches else None,
            "liveness_score": result.liveness_score,
            "camera_id":      req.camera_id,
            "location":       req.location,
            "identity_id":    result.matches[0].identity_id if result.matches else None,
        }
        event = await log_recognition_event(event_data)
        event_id = event["id"]
    except Exception as e:
        logger.warning(f"Log event échoué: {e}")

    return RecognizeResponse(
        success=result.success,
        event_type=event_type,
        face_count=result.face_count,
        matches=[
            MatchInfo(
                identity_id=m.identity_id,
                full_name=m.full_name,
                role=m.role,
                similarity=m.similarity,
            )
            for m in result.matches
        ],
        unknown_id=result.unknown_ids[0] if result.unknown_ids else None,
        is_live=result.is_live,
        liveness_score=result.liveness_score,
        quality_score=result.quality_score,
        processing_ms=result.processing_ms,
        event_id=event_id,
        error=result.error,
    )


@router.post("/upload", response_model=RecognizeResponse)
async def recognize_upload(
    file: UploadFile = File(..., description="Image JPEG/PNG"),
    camera_id: str = Form("default"),
    location: str = Form(None),
    check_liveness: bool = Form(True),
):
    """
    Reconnaissance depuis upload multipart (formulaire ou mobile).
    """
    content_type = file.content_type or ""
    if not content_type.startswith("image/"):
        raise HTTPException(400, "Fichier doit être une image (JPEG/PNG)")

    max_bytes = settings.max_image_size_mb * 1024 * 1024
    image_bytes = await file.read()

    if len(image_bytes) > max_bytes:
        raise HTTPException(413, f"Image trop grande (max {settings.max_image_size_mb}MB)")

    from pipeline import get_pipeline
    pipeline = get_pipeline()

    result = await pipeline.process_image_bytes(
        image_bytes, check_liveness=check_liveness
    )

    event_type = "rejected"
    if result.success:
        if not result.is_live:
            event_type = "spoof_detected"
        elif result.matches:
            event_type = "recognized"
        else:
            event_type = "unknown"

    event_id = None
    try:
        event = await log_recognition_event({
            "event_type":     event_type,
            "confidence":     result.matches[0].similarity if result.matches else None,
            "liveness_score": result.liveness_score,
            "camera_id":      camera_id,
            "location":       location,
            "identity_id":    result.matches[0].identity_id if result.matches else None,
        })
        event_id = event["id"]
    except Exception as e:
        logger.warning(f"Log event échoué: {e}")

    return RecognizeResponse(
        success=result.success,
        event_type=event_type,
        face_count=result.face_count,
        matches=[
            MatchInfo(
                identity_id=m.identity_id,
                full_name=m.full_name,
                role=m.role,
                similarity=m.similarity,
            )
            for m in result.matches
        ],
        unknown_id=result.unknown_ids[0] if result.unknown_ids else None,
        is_live=result.is_live,
        liveness_score=result.liveness_score,
        quality_score=result.quality_score,
        processing_ms=result.processing_ms,
        event_id=event_id,
        error=result.error,
    )
