"""
Router learning — active learning queue + drift reports.
Admin only.
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../ai-core"))

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth.dependencies import require_admin, AuthenticatedUser
from learning import (
    list_pending_corrections, apply_correction, CorrectionType,
    compute_identity_drift,
)


router = APIRouter(
    prefix="/api/v1/learning",
    tags=["Active learning / Drift"],
    dependencies=[Depends(require_admin)],
)


class CorrectionApply(BaseModel):
    correction_type:    str         # confirm | reassign | reject
    chosen_identity_id: str | None = None
    notes:              str | None = None


# ============================================================
# Active learning
# ============================================================

@router.get("/corrections")
async def list_corrections(limit: int = Query(100, ge=1, le=500)):
    return await list_pending_corrections(limit=limit)


@router.post("/corrections/{correction_id}/apply")
async def apply(correction_id: str, payload: CorrectionApply, user: AuthenticatedUser = Depends(require_admin)):
    try:
        ct = CorrectionType(payload.correction_type)
    except ValueError:
        raise HTTPException(400, f"correction_type invalide: {payload.correction_type}")

    try:
        return await apply_correction(
            correction_id=correction_id,
            correction_type=ct,
            chosen_identity_id=payload.chosen_identity_id,
            reviewer_id=user.user_id,
            notes=payload.notes,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


# ============================================================
# Drift
# ============================================================

@router.get("/drift/{identity_id}")
async def drift_for(identity_id: str, threshold: float = Query(0.78, ge=0.5, le=0.95)):
    report = await compute_identity_drift(identity_id, threshold=threshold)
    return {
        "identity_id":           report.identity_id,
        "n_baseline":            report.n_baseline,
        "n_recent":              report.n_recent,
        "baseline_cohesion":     report.baseline_centroid_sim,
        "recent_vs_baseline":    report.recent_vs_baseline_sim,
        "drift_detected":        report.drift_detected,
        "drift_threshold":       report.drift_threshold,
        "action":                report.action,
    }
