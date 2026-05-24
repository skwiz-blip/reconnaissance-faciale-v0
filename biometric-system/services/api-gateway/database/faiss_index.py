"""
FAISS Vector Index — cache local des embeddings pour recherche <1ms.

Pattern: write-through.
- Supabase reste la source de vérité (persistance).
- FAISS est un index en mémoire reconstruit au démarrage et maintenu à chaud
  lors des enrôlements / suppressions.
- Recherche 1:N en O(log N) sur 1M+ embeddings.

Structure de l'index:
    IndexIDMap2(IndexFlatIP)         pour < 100k embeddings (recall parfait)
    IndexIDMap2(IndexHNSWFlat)       pour ≥ 100k embeddings (recall ~99%, latence ms)

Les embeddings ArcFace sont déjà L2-normalisés → cosine == inner product.
"""
from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass
from typing import Optional

import faiss
import numpy as np
from loguru import logger


EMBEDDING_DIM = 512
HNSW_THRESHOLD = 100_000  # bascule Flat → HNSW au-delà


@dataclass(slots=True)
class FaissHit:
    embedding_id: str
    identity_id: str
    similarity: float


class FaissIndex:
    """
    Index FAISS thread-safe avec mapping bidirectionnel
    int64 (FAISS ID) ↔ UUID (Supabase).

    FAISS ne supporte que des IDs int64 ; on stocke donc un dict
    int64 → (embedding_uuid, identity_uuid).
    """

    def __init__(self, use_hnsw: bool = False):
        self._lock = threading.RLock()
        self._use_hnsw = use_hnsw
        self._index = self._build_empty_index(use_hnsw)
        self._id_to_meta: dict[int, tuple[str, str]] = {}
        self._uuid_to_id: dict[str, int] = {}
        self._next_id: int = 1
        self._last_sync: float = 0.0
        self._ready = False

    # --------------------------------------------------------
    # Construction
    # --------------------------------------------------------

    @staticmethod
    def _build_empty_index(use_hnsw: bool) -> faiss.Index:
        if use_hnsw:
            base = faiss.IndexHNSWFlat(EMBEDDING_DIM, 32, faiss.METRIC_INNER_PRODUCT)
            base.hnsw.efConstruction = 80
            base.hnsw.efSearch = 64
        else:
            base = faiss.IndexFlatIP(EMBEDDING_DIM)
        return faiss.IndexIDMap2(base)

    # --------------------------------------------------------
    # Synchronisation initiale depuis Supabase
    # --------------------------------------------------------

    async def reload_from_supabase(self) -> int:
        """
        Recharge l'intégralité de l'index depuis Supabase.
        Appelé au démarrage et périodiquement (sécurité contre les drifts).
        Déchiffre les embeddings AES-GCM si EMBEDDING_ENCRYPTION_ENABLED=true.
        """
        from database.supabase_client import get_supabase
        from security import decrypt_embedding, is_encryption_enabled

        sb = get_supabase()
        page_size = 1000
        offset = 0
        all_embeddings: list[tuple[str, str, list[float]]] = []
        encryption_on = is_encryption_enabled()

        while True:
            cols = "id, identity_id, embedding, identities!inner(status)"
            if encryption_on:
                cols = "id, identity_id, embedding, embedding_encrypted, identities!inner(status)"
            res = (
                sb.table("face_embeddings")
                .select(cols)
                .eq("identities.status", "active")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            rows = res.data or []
            if not rows:
                break
            for r in rows:
                if encryption_on and r.get("embedding_encrypted"):
                    try:
                        vec = decrypt_embedding(r["embedding_encrypted"]).tolist()
                    except Exception as e:
                        logger.warning(f"Déchiffrement {r['id']} échoué: {e}")
                        continue
                else:
                    vec = r["embedding"]
                if vec:
                    all_embeddings.append((r["id"], r["identity_id"], vec))
            if len(rows) < page_size:
                break
            offset += page_size

        with self._lock:
            n = len(all_embeddings)
            use_hnsw = n >= HNSW_THRESHOLD
            self._use_hnsw = use_hnsw
            self._index = self._build_empty_index(use_hnsw)
            self._id_to_meta.clear()
            self._uuid_to_id.clear()
            self._next_id = 1

            if n > 0:
                vectors = np.array(
                    [e[2] for e in all_embeddings], dtype=np.float32
                )
                ids = np.arange(self._next_id, self._next_id + n, dtype=np.int64)
                self._index.add_with_ids(vectors, ids)
                for fid, (emb_id, identity_id, _) in zip(ids, all_embeddings):
                    self._id_to_meta[int(fid)] = (emb_id, identity_id)
                    self._uuid_to_id[emb_id] = int(fid)
                self._next_id += n

            self._ready = True
            self._last_sync = time.time()

        logger.success(
            f"FAISS index chargé: {n} embeddings | "
            f"backend={'HNSW' if use_hnsw else 'FlatIP'}"
        )
        return n

    # --------------------------------------------------------
    # Mutations (write-through)
    # --------------------------------------------------------

    def add(self, embedding_id: str, identity_id: str, embedding: np.ndarray) -> None:
        """Ajoute un embedding à l'index. Idempotent sur embedding_id."""
        vec = self._normalize(embedding)
        with self._lock:
            if embedding_id in self._uuid_to_id:
                return  # déjà présent
            fid = self._next_id
            self._next_id += 1
            self._index.add_with_ids(
                vec.reshape(1, -1), np.array([fid], dtype=np.int64)
            )
            self._id_to_meta[fid] = (embedding_id, identity_id)
            self._uuid_to_id[embedding_id] = fid

    def remove_embedding(self, embedding_id: str) -> bool:
        with self._lock:
            fid = self._uuid_to_id.pop(embedding_id, None)
            if fid is None:
                return False
            self._index.remove_ids(np.array([fid], dtype=np.int64))
            self._id_to_meta.pop(fid, None)
            return True

    def remove_identity(self, identity_id: str) -> int:
        with self._lock:
            to_remove = [
                fid for fid, (_, iid) in self._id_to_meta.items()
                if iid == identity_id
            ]
            if not to_remove:
                return 0
            self._index.remove_ids(np.array(to_remove, dtype=np.int64))
            for fid in to_remove:
                emb_id, _ = self._id_to_meta.pop(fid)
                self._uuid_to_id.pop(emb_id, None)
            return len(to_remove)

    # --------------------------------------------------------
    # Recherche
    # --------------------------------------------------------

    def search(
        self,
        embedding: np.ndarray,
        k: int = 5,
        threshold: float = 0.6,
    ) -> list[FaissHit]:
        """
        Cherche les k embeddings les plus proches.
        Retourne les hits dont similarité > threshold.
        """
        if not self._ready or self._index.ntotal == 0:
            return []

        query = self._normalize(embedding).reshape(1, -1)
        with self._lock:
            # On cherche un peu plus large pour dédupliquer par identité ensuite
            scores, ids = self._index.search(query, min(k * 3, self._index.ntotal))

        hits: list[FaissHit] = []
        seen_identities: set[str] = set()
        for sim, fid in zip(scores[0], ids[0]):
            if fid < 0:
                continue
            if sim < threshold:
                continue
            meta = self._id_to_meta.get(int(fid))
            if not meta:
                continue
            emb_id, identity_id = meta
            if identity_id in seen_identities:
                continue  # garde le meilleur match par identité
            seen_identities.add(identity_id)
            hits.append(FaissHit(emb_id, identity_id, float(sim)))
            if len(hits) >= k:
                break
        return hits

    # --------------------------------------------------------
    # Introspection
    # --------------------------------------------------------

    @property
    def size(self) -> int:
        return self._index.ntotal

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def backend(self) -> str:
        return "HNSW" if self._use_hnsw else "FlatIP"

    def stats(self) -> dict:
        return {
            "size": self.size,
            "ready": self._ready,
            "backend": self.backend,
            "last_sync_ago_s": round(time.time() - self._last_sync, 1) if self._last_sync else None,
            "identities": len({iid for _, iid in self._id_to_meta.values()}),
        }

    # --------------------------------------------------------
    # Utils
    # --------------------------------------------------------

    @staticmethod
    def _normalize(vec: np.ndarray) -> np.ndarray:
        vec = np.asarray(vec, dtype=np.float32).reshape(-1)
        norm = np.linalg.norm(vec)
        if norm < 1e-9:
            return vec
        return vec / norm


# --------------------------------------------------------
# Singleton + tâche de re-synchronisation
# --------------------------------------------------------

_index: Optional[FaissIndex] = None
_sync_task: Optional[asyncio.Task] = None


def get_faiss_index() -> FaissIndex:
    global _index
    if _index is None:
        _index = FaissIndex()
    return _index


async def start_faiss(resync_interval_s: int = 600) -> None:
    """
    Démarre l'index FAISS (au lifespan FastAPI):
      1. Reload complet depuis Supabase
      2. Lance la tâche de re-synchronisation périodique
    """
    global _sync_task
    idx = get_faiss_index()
    try:
        await idx.reload_from_supabase()
    except Exception as e:
        logger.error(f"FAISS reload initial échoué: {e}")

    async def _periodic_resync():
        while True:
            await asyncio.sleep(resync_interval_s)
            try:
                await idx.reload_from_supabase()
            except Exception as e:
                logger.warning(f"FAISS resync échoué: {e}")

    if _sync_task is None or _sync_task.done():
        _sync_task = asyncio.create_task(_periodic_resync())


async def stop_faiss() -> None:
    global _sync_task
    if _sync_task and not _sync_task.done():
        _sync_task.cancel()
        try:
            await _sync_task
        except asyncio.CancelledError:
            pass
    _sync_task = None
