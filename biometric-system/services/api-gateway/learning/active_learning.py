"""
Active learning queue — capture les cas ambigus pour amélioration humaine.

Quand le pipeline renvoie un match "borderline" (similarité proche du seuil,
ou plusieurs candidats avec scores serrés), on enregistre une "correction
candidate" pour révision admin. Une fois corrigée:
    - Si admin confirme l'identité top1 → ajout au profil biométrique (nouveau
      embedding "validé manuellement")
    - Si admin corrige (autre identité) → ajout au bon profil + correction du
      mauvais cas pour le fine-tuning futur
    - Si admin rejette → marque l'événement comme négatif

Bénéfices:
    - Le modèle "apprend" progressivement les variations (vieillissement,
      coiffure, lunettes) sans ré-enroller manuellement.
    - Constitue un dataset propre pour le fine-tuning ArcFace ultérieur.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import numpy as np
from loguru import logger

from database.supabase_client import get_supabase


class CorrectionType(str, Enum):
    CONFIRM   = "confirm"     # admin valide le top-1
    REASSIGN  = "reassign"    # admin choisit une autre identité
    REJECT    = "reject"      # admin marque comme faux positif (inconnu)


# Plage de scores "borderline" : exemple seuil = 0.6
#   - haut: 0.6  (juste sous-seuil → on aurait rejeté à tort ?)
#   - haut: 0.72 (juste au-dessus → reconnu mais incertain)
BORDERLINE_BAND = (0.55, 0.72)


# ============================================================
# Ingestion
# ============================================================

async def queue_correction_candidate(
    event_id: str,
    predicted_identity_id: Optional[str],
    top_similarity: float,
    embedding: np.ndarray,
    candidates: list[dict],
    tenant_id: Optional[str] = None,
    image_url: Optional[str] = None,
) -> Optional[dict]:
    """
    Enregistre un cas borderline pour révision admin.
    Retourne le record ou None si pas borderline.
    """
    lo, hi = BORDERLINE_BAND
    if not (lo <= top_similarity <= hi):
        return None

    sb = get_supabase()
    payload = {
        "event_id":            event_id,
        "predicted_identity_id": predicted_identity_id,
        "top_similarity":      top_similarity,
        "embedding_snapshot":  embedding.tolist(),
        "candidates":          candidates,      # [{identity_id, similarity}, ...]
        "image_url":           image_url,
        "tenant_id":           tenant_id,
        "status":              "pending",
    }
    try:
        res = sb.table("correction_candidates").insert(payload).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.warning(f"Active learning queue échec: {e}")
        return None


# ============================================================
# Lecture
# ============================================================

async def list_pending_corrections(
    tenant_id: Optional[str] = None, limit: int = 100,
) -> list[dict]:
    sb = get_supabase()
    q = (
        sb.table("correction_candidates")
        .select("*")
        .eq("status", "pending")
        .order("created_at", desc=False)
        .limit(limit)
    )
    if tenant_id:
        q = q.eq("tenant_id", tenant_id)
    return q.execute().data or []


# ============================================================
# Application correction
# ============================================================

async def apply_correction(
    correction_id: str,
    correction_type: CorrectionType,
    chosen_identity_id: Optional[str],
    reviewer_id: str,
    notes: Optional[str] = None,
) -> dict:
    """
    Applique la décision admin:
      - CONFIRM/REASSIGN → ajoute l'embedding au profil cible (renforce)
      - REJECT → marque l'événement, pas d'enrôlement
    Met à jour FAISS via le service de recherche.
    """
    sb = get_supabase()
    candidate = sb.table("correction_candidates").select("*").eq("id", correction_id).single().execute()
    if not candidate.data:
        raise ValueError("Correction introuvable")
    c = candidate.data
    if c["status"] != "pending":
        raise ValueError(f"Correction déjà traitée: {c['status']}")

    embed_id: Optional[str] = None
    target_id: Optional[str] = None

    if correction_type in (CorrectionType.CONFIRM, CorrectionType.REASSIGN):
        target_id = chosen_identity_id or c["predicted_identity_id"]
        if not target_id:
            raise ValueError("identity_id requis pour CONFIRM/REASSIGN")

        from database.supabase_client import save_embedding
        from services.search_service import add_embedding_to_index
        emb = np.array(c["embedding_snapshot"], dtype=np.float32)

        saved = await save_embedding(
            identity_id=target_id, embedding=emb, quality=0.75,
            source=f"active_learning_{correction_type.value}",
        )
        await add_embedding_to_index(saved["id"], target_id, emb)
        embed_id = saved["id"]

    # Update correction
    update = {
        "status":             "applied",
        "correction_type":    correction_type.value,
        "chosen_identity_id": target_id,
        "reviewer_id":        reviewer_id,
        "notes":              notes,
        "applied_at":         datetime.now(timezone.utc).isoformat(),
        "new_embedding_id":   embed_id,
    }
    res = sb.table("correction_candidates").update(update).eq("id", correction_id).execute()
    return res.data[0] if res.data else {}
