"""
Router liveness challenges — défi-réponse pour anti-spoof actif.

Flow:
    1. POST /liveness/challenges        → émet un challenge (blink, turn_left, …)
    2. POST /liveness/challenges/submit → envoie une frame, reçoit progress/status
    3. GET  /liveness/challenges/{id}   → consulte l'état
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../ai-core"))

import base64
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger

from auth.dependencies import require_user, AuthenticatedUser
from database.supabase_client import get_supabase
from models.schemas_v3 import (
    IssueChallengeRequest, ChallengeStatusResponse,
    SubmitChallengeFrameRequest,
    ChallengeActionEnum, ChallengeStatusEnum,
)


router = APIRouter(
    prefix="/api/v1/liveness",
    tags=["Liveness challenges"],
    dependencies=[Depends(require_user)],
)


def _decode_b64(s: str):
    import cv2
    import numpy as np
    if "," in s:
        s = s.split(",", 1)[1]
    arr = np.frombuffer(base64.b64decode(s), np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def _to_response(attempt) -> ChallengeStatusResponse:
    return ChallengeStatusResponse(
        challenge_id=attempt.challenge_id,
        action=ChallengeActionEnum(attempt.action.value),
        status=ChallengeStatusEnum(attempt.status.value),
        progress=round(attempt.progress, 3),
        expires_at=datetime.fromtimestamp(attempt.expires_at, tz=timezone.utc),
        started_at=datetime.fromtimestamp(attempt.started_at, tz=timezone.utc),
        issued_for=attempt.metadata.get("issued_for"),
    )


@router.post("/challenges", response_model=ChallengeStatusResponse, status_code=201)
async def issue_challenge(req: IssueChallengeRequest, user: AuthenticatedUser = Depends(require_user)):
    from liveness_v2 import get_challenger, ChallengeAction

    action = ChallengeAction(req.action.value) if req.action else None
    attempt = get_challenger().issue(action)
    attempt.metadata["issued_for"] = req.issued_for
    attempt.metadata["issued_by"]  = user.user_id

    # Persistance
    try:
        get_supabase().table("liveness_challenges").insert({
            "challenge_id": attempt.challenge_id,
            "action":       attempt.action.value,
            "status":       attempt.status.value,
            "issued_to":    req.identity_id,
            "issued_for":   req.issued_for,
            "expires_at":   datetime.fromtimestamp(attempt.expires_at, tz=timezone.utc).isoformat(),
            "metadata":     {"issued_by": user.user_id},
        }).execute()
    except Exception as e:
        logger.warning(f"Persist challenge: {e}")

    return _to_response(attempt)


@router.post("/challenges/submit", response_model=ChallengeStatusResponse)
async def submit_frame(req: SubmitChallengeFrameRequest, user: AuthenticatedUser = Depends(require_user)):
    from liveness_v2 import get_challenger
    from detector import get_detector

    challenger = get_challenger()
    if challenger.get(req.challenge_id) is None:
        raise HTTPException(404, "Challenge introuvable")

    img = _decode_b64(req.image_base64)
    if img is None:
        raise HTTPException(400, "Image non décodable")

    faces = get_detector().detect(img)
    landmarks = faces[0].landmarks if faces else None
    face_crop = faces[0].face_img if faces else img

    try:
        attempt = challenger.submit_frame(req.challenge_id, face_crop, landmarks)
    except ValueError as e:
        raise HTTPException(404, str(e))

    # Sync en DB (best effort)
    try:
        update = {
            "status":          attempt.status.value,
            "progress":        attempt.progress,
            "frames_received": attempt.metadata.get("frames_seen", 0),
        }
        if attempt.status.value == "passed":
            update["completed_at"] = datetime.now(timezone.utc).isoformat()
        get_supabase().table("liveness_challenges").update(update).eq(
            "challenge_id", req.challenge_id
        ).execute()
    except Exception as e:
        logger.debug(f"Sync challenge: {e}")

    return _to_response(attempt)


@router.get("/challenges/{challenge_id}", response_model=ChallengeStatusResponse)
async def get_challenge(challenge_id: str, user: AuthenticatedUser = Depends(require_user)):
    from liveness_v2 import get_challenger
    attempt = get_challenger().get(challenge_id)
    if attempt is None:
        # Peut être en DB mais évincé de la mémoire — on essaie Supabase
        res = get_supabase().table("liveness_challenges").select("*").eq("challenge_id", challenge_id).execute()
        if not res.data:
            raise HTTPException(404, "Challenge introuvable")
        row = res.data[0]
        return ChallengeStatusResponse(
            challenge_id=row["challenge_id"],
            action=ChallengeActionEnum(row["action"]),
            status=ChallengeStatusEnum(row["status"]),
            progress=row.get("progress", 0.0),
            expires_at=row["expires_at"],
            started_at=row["issued_at"],
            issued_for=row.get("issued_for"),
        )
    return _to_response(attempt)
