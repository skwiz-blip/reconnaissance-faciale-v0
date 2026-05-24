"""
Clustering DBSCAN des visages inconnus.

Problème: au fil du temps, le même inconnu peut apparaître dizaines de fois
avec des embeddings légèrement différents (angle, lumière, expression).
On regroupe ces apparitions en clusters → un seul "Unknown_42" représente
toutes les apparitions du même individu.

Algo: DBSCAN avec métrique cosine (eps = 1 - similarity_threshold).
DBSCAN tolère le bruit (points "outliers") et ne nécessite pas de connaître
le nombre de clusters à l'avance.

Pipeline:
    1. Récupérer tous les unknowns non résolus
    2. Normaliser les embeddings
    3. DBSCAN → labels (-1 = bruit, 0..N = cluster)
    4. Pour chaque cluster: choisir un représentant (médoïde)
    5. Mettre à jour `cluster_id` sur chaque ligne unknown_faces
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np
from loguru import logger
from sklearn.cluster import DBSCAN


@dataclass(slots=True)
class ClusterResult:
    n_clusters: int
    n_noise: int
    n_processed: int
    cluster_sizes: dict[str, int]


def cluster_unknowns(
    embeddings: np.ndarray,
    similarity_threshold: float = 0.65,
    min_samples: int = 2,
) -> np.ndarray:
    """
    Retourne un array de labels (int), même longueur que `embeddings`.
    Label -1 = bruit (apparition isolée).

    Args:
        embeddings: shape (N, 512), supposés L2-normalisés.
        similarity_threshold: 1 - eps. 0.65 = visages assez similaires pour
            être considérés comme la même personne.
        min_samples: nombre min d'apparitions pour former un cluster.
    """
    if len(embeddings) == 0:
        return np.array([], dtype=int)

    # Distance cosine = 1 - similarité.
    # On veut grouper si sim > threshold, donc eps = 1 - threshold.
    eps = 1.0 - similarity_threshold
    db = DBSCAN(eps=eps, min_samples=min_samples, metric="cosine", n_jobs=-1)
    return db.fit_predict(embeddings)


def medoid_index(embeddings: np.ndarray, member_indices: np.ndarray) -> int:
    """
    Index (dans embeddings) du médoïde d'un cluster — l'embedding
    qui minimise la distance moyenne aux autres membres.
    """
    if len(member_indices) == 1:
        return int(member_indices[0])
    members = embeddings[member_indices]
    # Matrice de similarité (les embeddings sont normalisés)
    sims = members @ members.T
    # On veut maximiser la similarité moyenne (= minimiser distance)
    scores = sims.mean(axis=1)
    return int(member_indices[int(np.argmax(scores))])


async def run_clustering_pass(
    similarity_threshold: float = 0.65,
    min_samples: int = 2,
    batch_limit: int = 5000,
) -> ClusterResult:
    """
    Tâche complète: lit Supabase → clusterise → écrit les cluster_id.
    Idempotente: peut être ré-exécutée, recalcule à neuf.
    """
    from database.supabase_client import get_supabase

    sb = get_supabase()
    res = (
        sb.table("unknown_faces")
        .select("id, embedding")
        .eq("resolved", False)
        .limit(batch_limit)
        .execute()
    )
    rows = res.data or []

    if not rows:
        return ClusterResult(0, 0, 0, {})

    ids = [r["id"] for r in rows]
    embeddings = np.array([r["embedding"] for r in rows], dtype=np.float32)

    # Re-normalisation défensive
    norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
    norms[norms < 1e-9] = 1.0
    embeddings = embeddings / norms

    labels = cluster_unknowns(embeddings, similarity_threshold, min_samples)
    unique = set(labels) - {-1}
    n_noise = int(np.sum(labels == -1))

    cluster_sizes: dict[str, int] = {}
    updates: list[tuple[str, Optional[str]]] = []

    for label in unique:
        member_idx = np.where(labels == label)[0]
        cluster_id = f"cluster_{label:04d}"
        cluster_sizes[cluster_id] = int(len(member_idx))
        for idx in member_idx:
            updates.append((ids[idx], cluster_id))

    # Outliers: reset cluster_id
    for idx in np.where(labels == -1)[0]:
        updates.append((ids[idx], None))

    # Updates groupés (par lots de 100 pour éviter timeouts)
    for i in range(0, len(updates), 100):
        chunk = updates[i:i + 100]
        for row_id, cluster_id in chunk:
            try:
                sb.table("unknown_faces").update(
                    {"cluster_id": cluster_id}
                ).eq("id", row_id).execute()
            except Exception as e:
                logger.warning(f"Update cluster_id {row_id}: {e}")

    logger.success(
        f"Clustering: {len(unique)} clusters, {n_noise} bruit, "
        f"{len(rows)} inconnus traités"
    )
    return ClusterResult(
        n_clusters=len(unique),
        n_noise=n_noise,
        n_processed=len(rows),
        cluster_sizes=cluster_sizes,
    )
