"""
Face matching selfie ↔ photo du document.

Pipeline:
  1. Détection visage sur selfie (généralement 1)
  2. Détection visage sur document (souvent partiel, qualité réduite)
  3. Génération d'embeddings ArcFace (réutilise le pipeline existant)
  4. Similarité cosine
  5. Décision (match si > seuil KYC, plus exigeant que le seuil reco standard)

Le seuil KYC est plus strict (0.70+) que la reconnaissance simple (0.60)
car un faux positif KYC = ouverture frauduleuse de compte.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import cv2
import numpy as np
from loguru import logger


@dataclass(slots=True)
class FaceMatchResult:
    is_match:          bool
    similarity:        float
    selfie_quality:    float
    document_quality:  float
    threshold_used:    float
    selfie_face_count: int
    doc_face_count:    int
    reason:            str = ""


KYC_DEFAULT_THRESHOLD = 0.70


def compare_selfie_to_document(
    selfie_img: np.ndarray,
    document_img: np.ndarray,
    threshold: float = KYC_DEFAULT_THRESHOLD,
    min_quality: float = 0.25,
) -> FaceMatchResult:
    """
    Renvoie le verdict de face matching KYC.
    Utilise les détecteurs InsightFace + embeddings ArcFace via les
    singletons existants.
    """
    from detector import get_detector
    from embedder import get_embedder

    detector = get_detector()
    embedder = get_embedder()

    selfie_faces = detector.detect(selfie_img) if selfie_img is not None else []
    doc_faces = detector.detect(document_img) if document_img is not None else []

    if not selfie_faces:
        return FaceMatchResult(False, 0.0, 0.0, 0.0, threshold, 0, len(doc_faces),
                               "Aucun visage détecté sur le selfie")
    if not doc_faces:
        return FaceMatchResult(False, 0.0, selfie_faces[0].quality_score, 0.0,
                               threshold, len(selfie_faces), 0,
                               "Aucun visage détecté sur le document")

    # On prend le visage principal (meilleur score) sur chaque image
    selfie = selfie_faces[0]
    doc = doc_faces[0]

    if selfie.quality_score < min_quality:
        return FaceMatchResult(
            False, 0.0, selfie.quality_score, doc.quality_score,
            threshold, len(selfie_faces), len(doc_faces),
            f"Qualité selfie insuffisante ({selfie.quality_score:.2f})",
        )

    # Embeddings (InsightFace les calcule déjà à la détection si disponible)
    emb_selfie = selfie.embedding if selfie.embedding is not None else embedder.embed(selfie.face_img)
    emb_doc = doc.embedding if doc.embedding is not None else embedder.embed(doc.face_img)
    if emb_selfie is None or emb_doc is None:
        return FaceMatchResult(False, 0.0, selfie.quality_score, doc.quality_score,
                               threshold, len(selfie_faces), len(doc_faces),
                               "Échec de génération d'embedding")

    # Normalisation L2
    emb_selfie = emb_selfie / (np.linalg.norm(emb_selfie) + 1e-9)
    emb_doc = emb_doc / (np.linalg.norm(emb_doc) + 1e-9)
    similarity = float(emb_selfie @ emb_doc)

    is_match = similarity >= threshold
    reason = (f"similarité={similarity:.3f} ≥ seuil={threshold:.2f}"
              if is_match else
              f"similarité={similarity:.3f} < seuil={threshold:.2f}")

    return FaceMatchResult(
        is_match=is_match,
        similarity=round(similarity, 4),
        selfie_quality=round(selfie.quality_score, 3),
        document_quality=round(doc.quality_score, 3),
        threshold_used=threshold,
        selfie_face_count=len(selfie_faces),
        doc_face_count=len(doc_faces),
        reason=reason,
    )
