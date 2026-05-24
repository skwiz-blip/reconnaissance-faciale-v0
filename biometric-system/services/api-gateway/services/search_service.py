"""
Service de recherche unifié.

Hiérarchie:
  1. FAISS (chemin chaud, <1ms) — utilisé si l'index est prêt.
  2. Supabase pgvector (fallback, ~50ms) — si FAISS indisponible.

Hydrate les hits FAISS (qui ne contiennent que des UUID) avec les métadonnées
identités (nom, rôle, statut) via Redis cache puis Supabase.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from loguru import logger

from database import faiss_index, redis_cache
from database.supabase_client import (
    get_supabase,
    search_face_embedding as supabase_search,
)


@dataclass(slots=True)
class IdentityHit:
    identity_id: str
    full_name: str
    role: str
    status: str
    similarity: float
    embedding_id: Optional[str] = None
    source: str = "faiss"  # "faiss" | "supabase"


# ============================================================
# Recherche
# ============================================================

async def search_identities(
    embedding: np.ndarray,
    threshold: float = 0.6,
    limit: int = 5,
) -> list[IdentityHit]:
    """
    Recherche optimisée. FAISS d'abord, fallback Supabase si vide ou KO.
    """
    idx = faiss_index.get_faiss_index()

    if idx.ready and idx.size > 0:
        try:
            faiss_hits = idx.search(embedding, k=limit, threshold=threshold)
            if faiss_hits:
                return await _hydrate_faiss_hits(faiss_hits)
            # Pas de match → on retourne vide sans appeler Supabase
            # (FAISS a l'index complet, donc pas la peine de refaire la recherche)
            return []
        except Exception as e:
            logger.warning(f"Recherche FAISS échouée, fallback Supabase: {e}")

    # Fallback: Supabase pgvector
    rows = await supabase_search(embedding, threshold=threshold, limit=limit)
    return [
        IdentityHit(
            identity_id=r["identity_id"],
            full_name=r["full_name"],
            role=r["role"],
            status=r["status"],
            similarity=float(r["similarity"]),
            embedding_id=r.get("embedding_id"),
            source="supabase",
        )
        for r in rows
    ]


# ============================================================
# Hydratation des hits FAISS
# ============================================================

async def _hydrate_faiss_hits(hits) -> list[IdentityHit]:
    """Récupère nom + rôle + statut pour chaque identity_id (Redis → Supabase)."""
    if not hits:
        return []

    identity_ids = [h.identity_id for h in hits]
    metadata: dict[str, dict] = {}

    # 1. Tenter le cache Redis
    missing: list[str] = []
    for iid in identity_ids:
        cached = await redis_cache.get_cached_identity(iid)
        if cached:
            metadata[iid] = cached
        else:
            missing.append(iid)

    # 2. Compléter via Supabase pour ce qui manque
    if missing:
        sb = get_supabase()
        try:
            res = (
                sb.table("identities")
                .select("id, full_name, role, status")
                .in_("id", missing)
                .execute()
            )
            for row in res.data or []:
                metadata[row["id"]] = row
                await redis_cache.set_cached_identity(row["id"], row, ttl=300)
        except Exception as e:
            logger.warning(f"Hydratation Supabase: {e}")

    # 3. Assembler
    out: list[IdentityHit] = []
    for h in hits:
        meta = metadata.get(h.identity_id)
        if not meta:
            continue  # identité supprimée entre-temps; ignorer
        if meta.get("status") != "active":
            continue  # FAISS contient seulement les actives, mais defensive check
        out.append(
            IdentityHit(
                identity_id=h.identity_id,
                full_name=meta["full_name"],
                role=meta["role"],
                status=meta["status"],
                similarity=h.similarity,
                embedding_id=h.embedding_id,
                source="faiss",
            )
        )
    return out


# ============================================================
# Maintenance index
# ============================================================

async def add_embedding_to_index(
    embedding_id: str, identity_id: str, embedding: np.ndarray
) -> None:
    """À appeler après save_embedding() pour garder FAISS à jour."""
    idx = faiss_index.get_faiss_index()
    if idx.ready:
        idx.add(embedding_id, identity_id, embedding)


async def remove_identity_from_index(identity_id: str) -> int:
    """À appeler après suppression d'une identité."""
    idx = faiss_index.get_faiss_index()
    n = idx.remove_identity(identity_id) if idx.ready else 0
    await redis_cache.invalidate_identity(identity_id)
    return n
