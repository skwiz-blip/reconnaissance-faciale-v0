"""
Détection de drift biométrique + auto re-enrôlement.

Une identité "drift" quand ses captures récentes (events) ont une similarité
moyenne avec ses embeddings de référence qui chute sous un seuil de stabilité
(par ex. < 0.78 alors que la baseline était 0.85). Causes typiques :
    - vieillissement (visage)
    - changement durable (barbe, lunettes)
    - dégradation qualité caméra

Stratégie:
    1. Pour chaque identité, agrège les K derniers events (avec embedding)
       sur N jours.
    2. Calcule la similarité moyenne par rapport au centroïde de référence.
    3. Si drift détecté, schedule un re-enrôlement automatique :
       on ajoute la moyenne des nouvelles captures comme nouvel embedding
       (avec quality_score réduit pour pondérer son influence).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
from loguru import logger

from database.supabase_client import get_supabase


@dataclass(slots=True)
class DriftReport:
    identity_id:        str
    n_baseline:         int
    n_recent:           int
    baseline_centroid_sim: float    # cohérence interne baseline (1.0 idéal)
    recent_vs_baseline_sim: float   # similarité récents → baseline
    drift_detected:     bool
    drift_threshold:    float
    action:             str         # "none" | "scheduled_reenroll"


# Constantes
DEFAULT_THRESHOLD = 0.78
LOOKBACK_DAYS = 30
MIN_RECENT_SAMPLES = 5


# ============================================================
# Calcul drift par identité
# ============================================================

async def compute_identity_drift(
    identity_id: str,
    threshold: float = DEFAULT_THRESHOLD,
    lookback_days: int = LOOKBACK_DAYS,
) -> DriftReport:
    sb = get_supabase()

    # Baseline = embeddings enrôlés (face_embeddings)
    base_res = (
        sb.table("face_embeddings")
        .select("embedding, quality_score")
        .eq("identity_id", identity_id)
        .order("created_at", desc=False)
        .execute()
    )
    baseline_rows = base_res.data or []
    if not baseline_rows:
        return DriftReport(identity_id, 0, 0, 0.0, 0.0, False, threshold, "no_baseline")

    baseline = np.array([r["embedding"] for r in baseline_rows], dtype=np.float32)
    baseline = _normalize_rows(baseline)
    centroid = baseline.mean(axis=0)
    centroid = centroid / (np.linalg.norm(centroid) + 1e-9)

    # Cohérence interne baseline
    base_sims = baseline @ centroid
    base_cohesion = float(np.mean(base_sims))

    # Captures récentes (recognition_events)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).isoformat()
    rec_res = (
        sb.table("recognition_events")
        .select("metadata, created_at")
        .eq("identity_id", identity_id)
        .gte("created_at", cutoff)
        .execute()
    )
    recent_embs: list[list[float]] = []
    for r in rec_res.data or []:
        emb = (r.get("metadata") or {}).get("embedding")
        if emb and isinstance(emb, list) and len(emb) == 512:
            recent_embs.append(emb)

    if len(recent_embs) < MIN_RECENT_SAMPLES:
        return DriftReport(identity_id, len(baseline_rows), len(recent_embs),
                           base_cohesion, 0.0, False, threshold, "insufficient_samples")

    recent = _normalize_rows(np.array(recent_embs, dtype=np.float32))
    recent_sim_to_centroid = float(np.mean(recent @ centroid))

    drift = recent_sim_to_centroid < threshold
    return DriftReport(
        identity_id=identity_id,
        n_baseline=len(baseline_rows),
        n_recent=len(recent_embs),
        baseline_centroid_sim=round(base_cohesion, 4),
        recent_vs_baseline_sim=round(recent_sim_to_centroid, 4),
        drift_detected=drift,
        drift_threshold=threshold,
        action="scheduled_reenroll" if drift else "none",
    )


# ============================================================
# Re-enrôlement automatique
# ============================================================

async def schedule_re_enrollment(
    identity_id: str, recent_embeddings: list[np.ndarray],
) -> Optional[dict]:
    """
    Ajoute un nouveau "embedding moyen récent" au profil pour suivre l'évolution.
    quality_score réduit (0.6) pour limiter l'influence sur la centroid initiale.
    """
    if len(recent_embeddings) < 3:
        return None

    from database.supabase_client import save_embedding
    from services.search_service import add_embedding_to_index

    mean = np.mean(np.stack(recent_embeddings), axis=0).astype(np.float32)
    mean = mean / (np.linalg.norm(mean) + 1e-9)
    saved = await save_embedding(
        identity_id=identity_id, embedding=mean, quality=0.6,
        source="drift_autoreenroll",
    )
    await add_embedding_to_index(saved["id"], identity_id, mean)
    logger.info(f"Re-enrôlement auto: identité {identity_id} → embedding {saved['id']}")
    return saved


# ============================================================
# Utils
# ============================================================

def _normalize_rows(m: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms < 1e-9] = 1.0
    return m / norms
