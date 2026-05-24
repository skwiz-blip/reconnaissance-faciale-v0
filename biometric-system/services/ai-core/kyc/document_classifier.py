"""
Classification de type de document d'identité.

Approche pragmatique sans modèle pré-entraîné dédié:
  - Aspect ratio (passeport: ~1.42, CI européenne: ~1.59, permis US: ~1.59)
  - Présence de MRZ (passeports + nouvelles CI)
  - Densité de texte + zone photo
  - Couleur dominante (palette: passeports plus colorés que permis)

Pour passer en production sérieuse, remplacer par un modèle CNN entraîné
sur un dataset documents (MIDV-500, par exemple).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import cv2
import numpy as np


class DocumentType(str, Enum):
    PASSPORT       = "passport"
    ID_CARD        = "id_card"
    DRIVER_LICENSE = "driver_license"
    RESIDENCE_PERMIT = "residence_permit"
    UNKNOWN        = "unknown"


@dataclass(slots=True)
class DocumentClassification:
    doc_type:   DocumentType
    confidence: float
    aspect_ratio: float
    has_mrz:    bool
    notes:      str = ""


class DocumentClassifier:
    # Aspect ratios standards (largeur / hauteur)
    PASSPORT_AR = (1.40, 1.45)         # ICAO TD3
    ID_CARD_AR  = (1.55, 1.62)         # ID-1 (carte bancaire format)
    LICENSE_AR  = (1.55, 1.62)

    def classify(self, img: np.ndarray) -> DocumentClassification:
        if img is None or img.size == 0:
            return DocumentClassification(DocumentType.UNKNOWN, 0.0, 0.0, False, "image vide")

        h, w = img.shape[:2]
        ar = w / h if h > 0 else 0.0
        has_mrz = self._detect_mrz_region(img)

        # Décisions
        confidence = 0.6
        notes = []

        if has_mrz:
            if self._in_range(ar, *self.PASSPORT_AR):
                doc = DocumentType.PASSPORT
                confidence = 0.85
            elif self._in_range(ar, *self.ID_CARD_AR):
                doc = DocumentType.ID_CARD
                confidence = 0.75
                notes.append("MRZ trouvée sur format CI")
            else:
                doc = DocumentType.PASSPORT
                confidence = 0.55
                notes.append("MRZ détectée mais aspect ratio atypique")
        else:
            if self._in_range(ar, *self.PASSPORT_AR):
                doc = DocumentType.PASSPORT
                confidence = 0.6
                notes.append("aspect passeport mais MRZ non détectée")
            elif self._in_range(ar, *self.ID_CARD_AR):
                # CI vs permis: tente une heuristique couleur (permis: plus monochrome)
                doc, conf2 = self._distinguish_card_or_license(img)
                confidence = conf2
            else:
                doc = DocumentType.UNKNOWN
                confidence = 0.3
                notes.append("aspect ratio hors standards")

        return DocumentClassification(
            doc_type=doc,
            confidence=round(confidence, 3),
            aspect_ratio=round(ar, 3),
            has_mrz=has_mrz,
            notes="; ".join(notes),
        )

    @staticmethod
    def _in_range(v: float, lo: float, hi: float) -> bool:
        return lo <= v <= hi

    @staticmethod
    def _detect_mrz_region(img: np.ndarray) -> bool:
        """
        Heuristique: en bas du document, cherche 2-3 lignes de texte monospace
        de largeur ≈ document complet. Approximé via projection horizontale
        des contours noirs.
        """
        try:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape
            # On regarde le tiers inférieur
            bottom = gray[int(h * 0.7):, :]
            _, bw = cv2.threshold(bottom, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            # Projection horizontale
            row_sum = bw.sum(axis=1) / 255.0
            # On cherche 2-3 lignes denses (>60% de la largeur)
            threshold = 0.55 * w
            dense_rows = np.where(row_sum > threshold)[0]
            if len(dense_rows) < 10:
                return False
            # Vérifier qu'on a au moins 2 segments distincts
            gaps = np.diff(dense_rows)
            n_segments = 1 + int(np.sum(gaps > 5))
            return n_segments >= 2
        except Exception:
            return False

    @staticmethod
    def _distinguish_card_or_license(img: np.ndarray) -> tuple[DocumentType, float]:
        """Heuristique: permis souvent + sobre que CI."""
        try:
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            sat = hsv[..., 1]
            # Saturation moyenne
            mean_sat = float(np.mean(sat))
            if mean_sat > 70:
                return DocumentType.ID_CARD, 0.55
            return DocumentType.DRIVER_LICENSE, 0.5
        except Exception:
            return DocumentType.UNKNOWN, 0.3


_classifier: Optional[DocumentClassifier] = None


def get_classifier() -> DocumentClassifier:
    global _classifier
    if _classifier is None:
        _classifier = DocumentClassifier()
    return _classifier


def classify_document(img: np.ndarray) -> DocumentClassification:
    return get_classifier().classify(img)
