"""
Router KYC — création de session, soumission selfie + document, verdict.

Flow:
    1. POST /kyc/sessions       → crée session + (optionnel) défi liveness
    2. POST /kyc/sessions/submit → uploade selfie + doc, lance le pipeline
    3. GET  /kyc/sessions/{id}  → suit le statut + verdict
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../ai-core"))

import asyncio
import base64
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from loguru import logger

from auth.dependencies import require_user, AuthenticatedUser
from database.supabase_client import get_supabase
from models.schemas_v3 import (
    KYCStartRequest, KYCStartResponse,
    KYCSubmitRequest, KYCVerdictResponse,
    ChallengeStatusResponse, ChallengeActionEnum, ChallengeStatusEnum,
)


router = APIRouter(
    prefix="/api/v1/kyc",
    tags=["KYC"],
    dependencies=[Depends(require_user)],
)


# ============================================================
# Helpers
# ============================================================

def _decode_b64(s: str) -> bytes:
    if "," in s:
        s = s.split(",", 1)[1]
    return base64.b64decode(s)


def _bytes_to_cv2(image_bytes: bytes):
    import cv2
    import numpy as np
    arr = np.frombuffer(image_bytes, np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


# ============================================================
# Endpoints
# ============================================================

@router.post("/sessions", response_model=KYCStartResponse, status_code=201)
async def start_kyc_session(req: KYCStartRequest, user: AuthenticatedUser = Depends(require_user)):
    """
    Démarre une session KYC. Génère un session_token (à transmettre côté
    client pour les soumissions) et, optionnellement, un challenge liveness.
    """
    sb = get_supabase()
    session_token = uuid.uuid4().hex

    record = sb.table("kyc_sessions").insert({
        "identity_id":     req.identity_id,
        "session_token":   session_token,
        "doc_type":        req.doc_type.value,
        "status":          "pending",
    }).execute()
    if not record.data:
        raise HTTPException(500, "Échec création session KYC")

    session = record.data[0]

    challenge_payload = None
    if req.issue_challenge:
        from liveness_v2 import get_challenger
        attempt = get_challenger().issue()
        try:
            sb.table("liveness_challenges").insert({
                "challenge_id":  attempt.challenge_id,
                "action":        attempt.action.value,
                "status":        attempt.status.value,
                "issued_to":     req.identity_id,
                "issued_for":    "kyc",
                "expires_at":    datetime.fromtimestamp(attempt.expires_at, tz=timezone.utc).isoformat(),
                "metadata":      {"session_token": session_token},
            }).execute()
            # Lien dans la session KYC
            sb.table("kyc_sessions").update({
                "challenge_id": attempt.challenge_id
            }).eq("id", session["id"]).execute()
        except Exception as e:
            logger.warning(f"KYC challenge enregistrement: {e}")

        challenge_payload = ChallengeStatusResponse(
            challenge_id=attempt.challenge_id,
            action=ChallengeActionEnum(attempt.action.value),
            status=ChallengeStatusEnum(attempt.status.value),
            progress=attempt.progress,
            expires_at=datetime.fromtimestamp(attempt.expires_at, tz=timezone.utc),
            started_at=datetime.fromtimestamp(attempt.started_at, tz=timezone.utc),
            issued_for="kyc",
        )

    return KYCStartResponse(
        session_id=session["id"],
        session_token=session_token,
        challenge=challenge_payload,
    )


@router.post("/sessions/submit", response_model=KYCVerdictResponse)
async def submit_kyc_session(
    req: KYCSubmitRequest,
    background: BackgroundTasks,
    user: AuthenticatedUser = Depends(require_user),
):
    """
    Soumet selfie + document. Exécute le pipeline KYC complet
    et persiste le verdict dans `kyc_sessions`.
    """
    sb = get_supabase()
    sess_res = (
        sb.table("kyc_sessions").select("*")
        .eq("session_token", req.session_token).single().execute()
    )
    if not sess_res.data:
        raise HTTPException(404, "Session KYC inconnue")
    session = sess_res.data
    if session["status"] in ("approved", "rejected"):
        raise HTTPException(409, f"Session déjà clôturée: {session['status']}")

    try:
        selfie_bytes = _decode_b64(req.selfie_base64)
        doc_bytes    = _decode_b64(req.document_base64)
        selfie_img   = _bytes_to_cv2(selfie_bytes)
        doc_img      = _bytes_to_cv2(doc_bytes)
        if selfie_img is None or doc_img is None:
            raise ValueError("Image non décodable")
    except Exception as e:
        raise HTTPException(400, f"Décodage image: {e}")

    # Marquer la session en cours
    sb.table("kyc_sessions").update({"status": "processing"}).eq("id", session["id"]).execute()

    # Lancer le pipeline en thread (cv2 + ONNX libèrent le GIL)
    from kyc.pipeline import get_kyc_pipeline
    pipeline = get_kyc_pipeline()

    verdict = await asyncio.to_thread(
        pipeline.verify, selfie_img, doc_img, session["doc_type"], True
    )

    # Persistance
    payload = {
        "status":           verdict.decision.value,
        "decision":         verdict.decision.value,
        "confidence":       verdict.confidence,
        "face_match_score": verdict.face_match.similarity if verdict.face_match else None,
        "liveness_passed":  verdict.liveness_passed,
        "classified_type":  verdict.classification.doc_type.value if verdict.classification else None,
        "risk_score":       verdict.fraud.risk_score if verdict.fraud else None,
        "fraud_flags":      [f.value for f in (verdict.fraud.flags if verdict.fraud else [])],
        "reasons":          verdict.reasons,
        "mrz_data":         None,
        "mrz_checks":       None,
        "ocr_data":         None,
    }
    if verdict.mrz:
        payload["mrz_data"]   = {
            "document_type":   verdict.mrz.document_type,
            "issuing_country": verdict.mrz.issuing_country,
            "surname":         verdict.mrz.surname,
            "given_names":     verdict.mrz.given_names,
            "document_number": verdict.mrz.document_number,
            "nationality":     verdict.mrz.nationality,
            "birth_date":      verdict.mrz.birth_date,
            "sex":             verdict.mrz.sex,
            "expiry_date":     verdict.mrz.expiry_date,
        }
        payload["mrz_checks"] = verdict.mrz.checks_passed
    if verdict.ocr:
        payload["ocr_data"] = {
            "engine":     verdict.ocr.engine,
            "confidence": verdict.ocr.confidence,
            "fields":     verdict.ocr.fields,
        }

    try:
        sb.table("kyc_sessions").update(payload).eq("id", session["id"]).execute()
    except Exception as e:
        logger.warning(f"Persist KYC verdict: {e}")

    # Audit
    background.add_task(_audit_kyc, user.user_id, user.role, session["id"], verdict.decision.value)

    return KYCVerdictResponse(
        session_id=session["id"],
        decision=verdict.decision.value,
        confidence=verdict.confidence,
        face_match_score=verdict.face_match.similarity if verdict.face_match else None,
        liveness_score=verdict.liveness_score,
        risk_score=verdict.fraud.risk_score if verdict.fraud else None,
        classified_type=verdict.classification.doc_type.value if verdict.classification else None,
        declared_type=session["doc_type"],
        fraud_flags=[f.value for f in (verdict.fraud.flags if verdict.fraud else [])],
        reasons=verdict.reasons,
        mrz=payload["mrz_data"],
        ocr_fields=verdict.ocr.fields if verdict.ocr else None,
    )


@router.get("/sessions/{session_id}", response_model=KYCVerdictResponse)
async def get_kyc_session(session_id: str, user: AuthenticatedUser = Depends(require_user)):
    sb = get_supabase()
    res = sb.table("kyc_sessions").select("*").eq("id", session_id).single().execute()
    if not res.data:
        raise HTTPException(404, "Session introuvable")
    s = res.data
    return KYCVerdictResponse(
        session_id=s["id"],
        decision=s.get("decision") or s.get("status") or "pending",
        confidence=s.get("confidence") or 0.0,
        face_match_score=s.get("face_match_score"),
        liveness_score=None,
        risk_score=s.get("risk_score"),
        classified_type=s.get("classified_type"),
        declared_type=s.get("doc_type"),
        fraud_flags=s.get("fraud_flags") or [],
        reasons=s.get("reasons") or [],
        mrz=s.get("mrz_data"),
        ocr_fields=(s.get("ocr_data") or {}).get("fields"),
    )


async def _audit_kyc(actor_id: str, role: str, session_id: str, decision: str) -> None:
    try:
        get_supabase().table("audit_logs").insert({
            "actor_id":    actor_id,
            "actor_role":  role,
            "action":      f"kyc.{decision}",
            "target_type": "kyc_session",
            "target_id":   session_id,
        }).execute()
    except Exception as e:
        logger.warning(f"Audit KYC: {e}")
