"""
Conformité RGPD — droit à l'oubli, export, anonymisation, consentement.

Couvre les obligations Art. 15 (accès), 17 (effacement), 20 (portabilité)
et 7 (consentement) du RGPD pour traitement biométrique (catégorie spéciale,
Art. 9).

Stratégies:
    - Effacement: suppression cascade (identities → face_embeddings → events)
      + anonymisation des logs (remplace identity_id par UUID null,
      garde la trace de l'événement pour audit légal mais sans rattachement).
    - Export: dump JSON complet (identité + embeddings chiffrés + événements
      + accès + KYC) pour portabilité.
    - Consentement: table `consents` avec historique horodaté.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from database.supabase_client import get_supabase


@dataclass(slots=True)
class ErasureReport:
    identity_id:         str
    embeddings_deleted:  int
    events_anonymized:   int
    access_logs_anonymized: int
    kyc_sessions_deleted: int
    unknown_faces_unlinked: int
    completed_at:        datetime


@dataclass(slots=True)
class ExportPackage:
    identity:        dict
    embeddings:      list[dict]
    recognition_events: list[dict]
    access_logs:     list[dict]
    kyc_sessions:    list[dict]
    consents:        list[dict]
    generated_at:    str


# ============================================================
# Effacement (Art. 17 — Right to be Forgotten)
# ============================================================

async def erase_identity(identity_id: str, reason: str = "user_request") -> ErasureReport:
    """
    Supprime toutes les données biométriques d'une identité et anonymise les logs.
    Évince aussi les vecteurs FAISS + cache Redis.
    """
    sb = get_supabase()

    # 1. Snapshot pour le retour
    embeds = sb.table("face_embeddings").select("id", count="exact").eq("identity_id", identity_id).execute()
    n_embeds = embeds.count or 0

    # 2. Supprimer face_embeddings (CASCADE depuis identities devrait suffire,
    # mais on le fait explicitement pour ne pas dépendre du schéma)
    sb.table("face_embeddings").delete().eq("identity_id", identity_id).execute()

    # 3. Anonymiser recognition_events (garde la trace mais coupe le lien)
    events_res = sb.table("recognition_events").update(
        {"identity_id": None, "metadata": {"erased_for_rgpd": True}}
    ).eq("identity_id", identity_id).execute()
    n_events = len(events_res.data or [])

    # 4. Anonymiser access_logs
    access_res = sb.table("access_logs").update(
        {"identity_id": None, "reason": "rgpd_erased"}
    ).eq("identity_id", identity_id).execute()
    n_access = len(access_res.data or [])

    # 5. Supprimer KYC sessions
    kyc_res = sb.table("kyc_sessions").delete().eq("identity_id", identity_id).execute()
    n_kyc = len(kyc_res.data or [])

    # 6. Délier les unknown_faces qui pointaient vers cette identité
    unk_res = sb.table("unknown_faces").update({"resolved_as": None}).eq("resolved_as", identity_id).execute()
    n_unk = len(unk_res.data or [])

    # 7. Supprimer l'identité elle-même
    sb.table("identities").delete().eq("id", identity_id).execute()

    # 8. Évincer FAISS + Redis
    try:
        from services.search_service import remove_identity_from_index
        await remove_identity_from_index(identity_id)
    except Exception as e:
        logger.warning(f"Eviction FAISS RGPD: {e}")

    # 9. Audit (anonymisé: pas d'identity_id puisqu'elle vient d'être effacée)
    try:
        sb.table("audit_logs").insert({
            "action": "rgpd.erase",
            "target_type": "identity",
            "target_id": identity_id,  # archivé pour traçabilité légale
            "metadata": {
                "reason": reason,
                "embeddings_deleted": n_embeds,
                "events_anonymized": n_events,
                "access_logs_anonymized": n_access,
                "kyc_sessions_deleted": n_kyc,
            },
        }).execute()
    except Exception as e:
        logger.warning(f"Audit RGPD: {e}")

    return ErasureReport(
        identity_id=identity_id,
        embeddings_deleted=n_embeds,
        events_anonymized=n_events,
        access_logs_anonymized=n_access,
        kyc_sessions_deleted=n_kyc,
        unknown_faces_unlinked=n_unk,
        completed_at=datetime.now(timezone.utc),
    )


# ============================================================
# Export (Art. 15 + 20 — Accès + Portabilité)
# ============================================================

async def export_identity(identity_id: str) -> ExportPackage:
    """Génère un dump JSON complet pour une identité."""
    sb = get_supabase()
    iden = sb.table("identities").select("*").eq("id", identity_id).single().execute()
    if not iden.data:
        raise ValueError("Identité introuvable")

    # NB: embeddings exportés en clair (les FORMATS chiffrés ne sont pas
    # portables vers d'autres systèmes). L'utilisateur reçoit ses propres
    # données biométriques en clair, sous sa responsabilité.
    from services.search_service import remove_identity_from_index  # noqa
    embeds = sb.table("face_embeddings").select("*").eq("identity_id", identity_id).execute()
    events = sb.table("recognition_events").select("*").eq("identity_id", identity_id).execute()
    access = sb.table("access_logs").select("*").eq("identity_id", identity_id).execute()
    kyc    = sb.table("kyc_sessions").select("*").eq("identity_id", identity_id).execute()
    consents = sb.table("consents").select("*").eq("identity_id", identity_id).execute()

    return ExportPackage(
        identity=iden.data,
        embeddings=embeds.data or [],
        recognition_events=events.data or [],
        access_logs=access.data or [],
        kyc_sessions=kyc.data or [],
        consents=consents.data or [],
        generated_at=datetime.now(timezone.utc).isoformat(),
    )


def export_to_json(pkg: ExportPackage) -> str:
    return json.dumps(pkg.__dict__, indent=2, default=str)


# ============================================================
# Anonymisation des logs (purge légère sans effacer)
# ============================================================

async def anonymize_logs(older_than_days: int) -> dict:
    """
    Coupe le lien identity_id ↔ logs vieux que N jours.
    Permet de conserver des stats agrégées sans données personnelles.
    """
    sb = get_supabase()
    res = sb.rpc("anonymize_old_logs", {"days_threshold": older_than_days}).execute()
    return res.data or {"anonymized": 0}


# ============================================================
# Consentement (Art. 7)
# ============================================================

async def record_consent(
    identity_id: str,
    purpose: str,
    granted: bool,
    document_url: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    sb = get_supabase()
    res = sb.table("consents").insert({
        "identity_id":  identity_id,
        "purpose":      purpose,           # ex: 'biometric_recognition', 'kyc', 'analytics'
        "granted":      granted,
        "document_url": document_url,
        "metadata":     metadata or {},
    }).execute()
    return res.data[0] if res.data else {}


async def get_consent(identity_id: str, purpose: str) -> Optional[dict]:
    """Retourne le consentement le plus récent pour un usage donné."""
    sb = get_supabase()
    res = (
        sb.table("consents").select("*")
        .eq("identity_id", identity_id).eq("purpose", purpose)
        .order("created_at", desc=True).limit(1).execute()
    )
    return res.data[0] if res.data else None


async def withdraw_consent(identity_id: str, purpose: str) -> dict:
    """Retire le consentement (enregistre un nouveau record granted=false)."""
    return await record_consent(
        identity_id=identity_id,
        purpose=purpose,
        granted=False,
        metadata={"withdrawal": True, "at": datetime.now(timezone.utc).isoformat()},
    )
