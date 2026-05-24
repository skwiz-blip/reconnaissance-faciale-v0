"""
Pipeline IA principal — orchestre détection → embedding → matching → anti-spoof
Point d'entrée unique pour toutes les opérations de reconnaissance.
"""
import cv2
import numpy as np
import base64
import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Optional
from loguru import logger

from detector import DetectedFace, get_detector
from embedder import get_embedder
from anti_spoof import get_liveness_detector


# ============================================================
# RÉSULTATS
# ============================================================

@dataclass
class MatchResult:
    identity_id: str
    full_name: str
    role: str
    status: str
    similarity: float
    is_match: bool


@dataclass
class PipelineResult:
    """Résultat complet d'une passe du pipeline"""
    success: bool
    faces: list[DetectedFace] = field(default_factory=list)

    # Résultats de reconnaissance
    matches: list[MatchResult] = field(default_factory=list)
    unknown_ids: list[str] = field(default_factory=list)

    # Anti-spoofing
    is_live: bool = True
    liveness_score: float = 1.0
    liveness_reason: str = ""

    # Embedding primary face
    embedding: Optional[np.ndarray] = None
    quality_score: float = 0.0

    # Méta
    face_count: int = 0
    processing_ms: float = 0.0
    error: Optional[str] = None


# ============================================================
# PIPELINE
# ============================================================

class BiometricPipeline:
    """
    Pipeline biométrique complet :
    1. Détection multi-visages
    2. Anti-spoofing (liveness)
    3. Génération d'embeddings
    4. Matching dans Supabase (via RPC pgvector)
    5. Gestion des inconnus
    """

    def __init__(self,
                 similarity_threshold: float = 0.6,
                 liveness_threshold: float = 0.5,
                 min_quality: float = 0.3):
        self.similarity_threshold = similarity_threshold
        self.liveness_threshold = liveness_threshold
        self.min_quality = min_quality
        self._unknown_counter = 0

    async def process_frame(self,
                             frame: np.ndarray,
                             check_liveness: bool = True,
                             camera_id: str = "default") -> PipelineResult:
        """
        Traite une frame complète.

        Args:
            frame: Image BGR numpy
            check_liveness: Active l'anti-spoof
            camera_id: Identifiant caméra pour le logging

        Returns:
            PipelineResult avec tous les résultats
        """
        import time
        t0 = time.perf_counter()

        if frame is None or frame.size == 0:
            return PipelineResult(success=False, error="Frame vide")

        result = PipelineResult(success=True)

        # ---- 1. Détection ----
        detector = get_detector()
        faces = detector.detect(frame)
        result.faces = faces
        result.face_count = len(faces)

        if not faces:
            return result

        # Travailler avec le visage principal (meilleure confiance)
        primary = faces[0]

        if primary.quality_score < self.min_quality:
            result.error = f"Qualité insuffisante ({primary.quality_score:.2f})"
            return result

        # ---- 2. Anti-spoofing ----
        if check_liveness:
            liveness = get_liveness_detector()
            liv_result = liveness.analyze(
                primary.face_img,
                landmarks=primary.landmarks
            )
            result.is_live = liv_result.is_live
            result.liveness_score = liv_result.score
            result.liveness_reason = liv_result.reason

            if not liv_result.is_live:
                result.error = f"Spoof détecté: {liv_result.reason}"
                logger.warning(f"[{camera_id}] SPOOF DÉTECTÉ score={liv_result.score:.2f}")
                return result

        # ---- 3. Embedding ----
        # Si InsightFace a déjà calculé l'embedding, on le récupère
        embedding = primary.embedding

        if embedding is None and primary.face_img is not None:
            embedder = get_embedder()
            embedding = embedder.embed(primary.face_img)

        if embedding is None:
            result.error = "Impossible de générer l'embedding"
            return result

        result.embedding = embedding
        result.quality_score = primary.quality_score

        # ---- 4. Matching (FAISS → fallback Supabase) ----
        import time as _t
        ts = _t.perf_counter()
        matches = await self._search_identity(embedding)
        try:
            from observability.metrics import faiss_search_seconds
            faiss_search_seconds.observe(_t.perf_counter() - ts)
        except Exception:
            pass
        result.matches = matches

        # ---- 5. Gestion inconnus ----
        if not matches:
            unknown_id = await self._handle_unknown(
                embedding, primary.face_img, camera_id
            )
            result.unknown_ids.append(unknown_id)
            logger.info(f"[{camera_id}] Inconnu enregistré: {unknown_id}")
        else:
            top = matches[0]
            logger.info(
                f"[{camera_id}] Reconnu: {top.full_name} "
                f"(sim={top.similarity:.3f})"
            )

        # Métriques Prometheus
        try:
            from observability.metrics import recognition_total
            event = ("recognized" if matches
                     else "spoof_detected" if not result.is_live
                     else "unknown")
            recognition_total.labels(event_type=event).inc()
        except Exception:
            pass

        result.processing_ms = round((time.perf_counter() - t0) * 1000, 1)
        return result

    async def process_image_bytes(self,
                                   image_bytes: bytes,
                                   check_liveness: bool = False) -> PipelineResult:
        """Traite une image depuis des bytes (upload API)"""
        nparr = np.frombuffer(image_bytes, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if frame is None:
            return PipelineResult(success=False, error="Image décodage échoué")
        return await self.process_frame(frame, check_liveness=check_liveness)

    async def process_base64(self,
                              b64_data: str,
                              check_liveness: bool = True) -> PipelineResult:
        """Traite une image encodée en base64"""
        try:
            # Enlever le header data:image/...;base64,
            if "," in b64_data:
                b64_data = b64_data.split(",")[1]
            image_bytes = base64.b64decode(b64_data)
            return await self.process_image_bytes(image_bytes, check_liveness)
        except Exception as e:
            return PipelineResult(success=False, error=f"Base64 decode: {e}")

    async def enroll_face(self,
                           image_bytes: bytes,
                           identity_id: str) -> dict:
        """
        Enrôle un nouveau visage pour une identité existante.
        Retourne les infos de l'embedding sauvegardé.
        """
        result = await self.process_image_bytes(image_bytes, check_liveness=False)

        if not result.success or result.embedding is None:
            return {"success": False, "error": result.error}

        if result.quality_score < self.min_quality:
            return {
                "success": False,
                "error": f"Qualité trop faible ({result.quality_score:.2f})"
            }

        # Sauvegarder dans Supabase puis pousser dans FAISS (write-through)
        from database.supabase_client import save_embedding
        from services.search_service import add_embedding_to_index

        emb_record = await save_embedding(
            identity_id=identity_id,
            embedding=result.embedding,
            quality=result.quality_score,
            source="enrollment",
            is_primary=(result.quality_score > 0.8),
        )
        await add_embedding_to_index(
            emb_record["id"], identity_id, result.embedding
        )

        return {
            "success": True,
            "embedding_id": emb_record["id"],
            "quality_score": result.quality_score,
            "face_count": result.face_count,
        }

    async def _search_identity(self, embedding: np.ndarray) -> list[MatchResult]:
        """
        Recherche unifiée: FAISS (chemin chaud) → fallback Supabase pgvector.
        Voir services/search_service.py pour le détail de la hiérarchie.
        """
        from services.search_service import search_identities
        hits = await search_identities(
            embedding, threshold=self.similarity_threshold, limit=5
        )
        return [
            MatchResult(
                identity_id=h.identity_id,
                full_name=h.full_name,
                role=h.role,
                status=h.status,
                similarity=h.similarity,
                is_match=True,
            )
            for h in hits
        ]

    async def _handle_unknown(self,
                               embedding: np.ndarray,
                               face_img: Optional[np.ndarray],
                               location: str) -> str:
        """
        Gère un visage inconnu :
        1. Cherche si c'est un inconnu déjà vu
        2. Sinon crée un nouvel Unknown_XXX
        """
        from database.supabase_client import (
            search_unknown_embedding, save_unknown_face
        )

        # Vérifier si déjà connu comme inconnu
        existing = await search_unknown_embedding(embedding, threshold=0.80)
        if existing:
            return existing[0]["temp_id"]

        # Nouvel inconnu
        self._unknown_counter += 1
        temp_id = f"Unknown_{self._unknown_counter:04d}"

        await save_unknown_face(
            temp_id=temp_id,
            embedding=embedding,
            location=location,
        )
        return temp_id

    @staticmethod
    def frame_from_bytes(data: bytes) -> Optional[np.ndarray]:
        nparr = np.frombuffer(data, np.uint8)
        return cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    @staticmethod
    def image_hash(image_bytes: bytes) -> str:
        return hashlib.sha256(image_bytes).hexdigest()


# Singleton
_pipeline: Optional[BiometricPipeline] = None


def get_pipeline() -> BiometricPipeline:
    global _pipeline
    if _pipeline is None:
        from config import get_settings
        s = get_settings()
        _pipeline = BiometricPipeline(
            similarity_threshold=s.similarity_threshold,
            liveness_threshold=s.liveness_threshold,
        )
    return _pipeline
