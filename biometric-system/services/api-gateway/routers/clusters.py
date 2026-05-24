"""
Router clusters: gestion du regroupement DBSCAN des visages inconnus.
Endpoints admin uniquement.
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../ai-core"))

from fastapi import APIRouter, Depends, HTTPException, Query
from loguru import logger
from pydantic import BaseModel, Field

from auth.dependencies import require_admin, AuthenticatedUser
from database.supabase_client import get_supabase


router = APIRouter(prefix="/api/v1/clusters", tags=["Clusters inconnus"])


class ClusterRunRequest(BaseModel):
    similarity_threshold: float = Field(0.65, ge=0.4, le=0.95)
    min_samples:          int = Field(2, ge=2, le=20)
    batch_limit:          int = Field(5000, ge=100, le=50000)


class ClusterRunResponse(BaseModel):
    n_clusters:     int
    n_noise:        int
    n_processed:    int
    cluster_sizes:  dict[str, int]


@router.post("/run", response_model=ClusterRunResponse)
async def run_clustering(
    req: ClusterRunRequest = ClusterRunRequest(),
    user: AuthenticatedUser = Depends(require_admin),
):
    """
    Lance une passe complète de clustering sur les visages inconnus non résolus.
    Opération idempotente — peut être exécutée plusieurs fois.
    """
    from clustering import run_clustering_pass
    logger.info(f"Clustering lancé par {user.user_id}")
    result = await run_clustering_pass(
        similarity_threshold=req.similarity_threshold,
        min_samples=req.min_samples,
        batch_limit=req.batch_limit,
    )
    return ClusterRunResponse(
        n_clusters=result.n_clusters,
        n_noise=result.n_noise,
        n_processed=result.n_processed,
        cluster_sizes=result.cluster_sizes,
    )


@router.get("")
async def list_clusters(
    limit: int = Query(50, ge=1, le=200),
    user: AuthenticatedUser = Depends(require_admin),
):
    """Liste les clusters d'inconnus avec leur taille."""
    sb = get_supabase()
    res = sb.rpc("list_clusters", {"max_count": limit}).execute()
    return res.data or []


@router.get("/{cluster_id}/faces")
async def list_cluster_faces(
    cluster_id: str,
    user: AuthenticatedUser = Depends(require_admin),
):
    """Liste les visages inconnus d'un cluster."""
    sb = get_supabase()
    res = (
        sb.table("unknown_faces")
        .select("id, temp_id, appearances, first_seen_at, last_seen_at, image_url, location")
        .eq("cluster_id", cluster_id)
        .eq("resolved", False)
        .order("appearances", desc=True)
        .execute()
    )
    if not res.data:
        raise HTTPException(404, "Cluster introuvable ou vide")
    return res.data


@router.post("/{cluster_id}/merge")
async def merge_cluster_to_identity(
    cluster_id: str,
    identity_id: str = Query(..., description="Identité cible"),
    user: AuthenticatedUser = Depends(require_admin),
):
    """
    Associe tous les visages d'un cluster à une identité existante.
    Transfère également les embeddings vers face_embeddings.
    """
    from database.supabase_client import save_embedding, resolve_unknown_face
    from services.search_service import add_embedding_to_index
    import numpy as np

    sb = get_supabase()

    # Vérifier l'identité
    iden = sb.table("identities").select("id").eq("id", identity_id).execute()
    if not iden.data:
        raise HTTPException(404, "Identité cible introuvable")

    # Charger les unknowns du cluster
    res = (
        sb.table("unknown_faces")
        .select("id, embedding")
        .eq("cluster_id", cluster_id)
        .eq("resolved", False)
        .execute()
    )
    rows = res.data or []
    if not rows:
        raise HTTPException(404, "Cluster vide ou déjà résolu")

    transferred = 0
    for r in rows:
        try:
            emb = np.array(r["embedding"], dtype=np.float32)
            saved = await save_embedding(
                identity_id, emb, quality=0.7, source="cluster_merge"
            )
            await add_embedding_to_index(saved["id"], identity_id, emb)
            await resolve_unknown_face(r["id"], identity_id)
            transferred += 1
        except Exception as e:
            logger.warning(f"Merge unknown {r['id']}: {e}")

    return {
        "cluster_id":   cluster_id,
        "identity_id":  identity_id,
        "transferred":  transferred,
        "total":        len(rows),
    }
