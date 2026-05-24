"""
Détection de fraude documentaire — heuristiques classiques.

Signaux levés:
  - LOW_RESOLUTION      : image trop petite (<800px)
  - BLURRY              : variance de Laplacien faible (flou)
  - SCREEN_CAPTURE      : présence de Moiré → photo d'écran
  - EDITED_REGION       : tâches de manipulation détectées (ELA)
  - MRZ_CHECKSUM_FAIL   : checksum MRZ invalide (transmis depuis le parser)
  - DOC_MISMATCH        : type document détecté ≠ type déclaré
  - NO_FACE_ON_DOCUMENT : pas de photo détectée sur le doc
  - DATE_INCONSISTENT   : expiration < aujourd'hui ou birth > aujourd'hui

Approche ELA (Error Level Analysis) simplifiée: recompresse l'image en JPEG
de qualité 90 puis mesure les différences. Les zones éditées (collages,
faux noms) ressortent comme des "hotspots" de différence.
"""
from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import cv2
import numpy as np


class FraudFlag(str, Enum):
    LOW_RESOLUTION      = "LOW_RESOLUTION"
    BLURRY              = "BLURRY"
    SCREEN_CAPTURE      = "SCREEN_CAPTURE"
    EDITED_REGION       = "EDITED_REGION"
    MRZ_CHECKSUM_FAIL   = "MRZ_CHECKSUM_FAIL"
    DOC_MISMATCH        = "DOC_MISMATCH"
    NO_FACE_ON_DOCUMENT = "NO_FACE_ON_DOCUMENT"
    DATE_INCONSISTENT   = "DATE_INCONSISTENT"
    EXPIRED_DOCUMENT    = "EXPIRED_DOCUMENT"


@dataclass(slots=True)
class FraudReport:
    flags:       list[FraudFlag] = field(default_factory=list)
    risk_score:  float = 0.0          # 0 = sûr, 1 = très suspect
    metrics:     dict[str, float] = field(default_factory=dict)
    notes:       list[str] = field(default_factory=list)

    def add(self, flag: FraudFlag, note: str = "") -> None:
        if flag not in self.flags:
            self.flags.append(flag)
        if note:
            self.notes.append(f"{flag}: {note}")

    def as_dict(self) -> dict:
        return {
            "flags":      [f.value for f in self.flags],
            "risk_score": round(self.risk_score, 3),
            "metrics":    {k: round(float(v), 3) for k, v in self.metrics.items()},
            "notes":      self.notes,
        }


# ============================================================
# Heuristiques unitaires
# ============================================================

MIN_DIMENSION = 800
BLUR_THRESHOLD = 60.0
ELA_HOTSPOT_THRESHOLD = 0.18


def _resolution_check(img: np.ndarray, report: FraudReport) -> None:
    h, w = img.shape[:2]
    if max(h, w) < MIN_DIMENSION:
        report.add(FraudFlag.LOW_RESOLUTION, f"{w}x{h}")
        report.risk_score += 0.15
    report.metrics["max_dimension"] = max(h, w)


def _blur_check(img: np.ndarray, report: FraudReport) -> None:
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    report.metrics["laplacian_variance"] = var
    if var < BLUR_THRESHOLD:
        report.add(FraudFlag.BLURRY, f"variance={var:.1f}")
        report.risk_score += 0.20


def _screen_capture_check(img: np.ndarray, report: FraudReport) -> None:
    """Patterns Moiré typiques d'une photo d'écran."""
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
    gray = cv2.resize(gray, (256, 256))
    f = np.fft.fft2(gray)
    fshift = np.fft.fftshift(f)
    spectrum = np.log1p(np.abs(fshift))
    h, w = spectrum.shape
    cy, cx = h // 2, w // 2
    mask = np.zeros_like(spectrum)
    cv2.circle(mask, (cx, cy), 60, 1, -1)
    cv2.circle(mask, (cx, cy), 20, 0, -1)
    mid = spectrum * mask
    score = float(np.var(mid[mid > 0])) if np.any(mid > 0) else 0.0
    report.metrics["moire_score"] = score
    if score > 5.5:
        report.add(FraudFlag.SCREEN_CAPTURE, f"moire={score:.2f}")
        report.risk_score += 0.25


def _ela_check(img: np.ndarray, report: FraudReport) -> None:
    """
    Error Level Analysis — détecte des zones recompressées différemment
    du reste de l'image (souvent les noms/photos modifiés).
    """
    try:
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
        if not ok:
            return
        recompressed = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        diff = cv2.absdiff(img, recompressed).astype(np.float32)
        diff_gray = diff.mean(axis=2) if diff.ndim == 3 else diff
        diff_norm = diff_gray / (diff_gray.max() + 1e-9)
        # Proportion de pixels "hotspot"
        hotspots = float(np.mean(diff_norm > 0.6))
        report.metrics["ela_hotspot_ratio"] = hotspots
        if hotspots > ELA_HOTSPOT_THRESHOLD:
            report.add(FraudFlag.EDITED_REGION, f"hotspots={hotspots:.3f}")
            report.risk_score += 0.30
    except Exception:
        pass


def _date_checks(mrz_birth: Optional[str], mrz_expiry: Optional[str], report: FraudReport) -> None:
    """MRZ dates au format YYMMDD."""
    today = datetime.now(timezone.utc).date()
    try:
        if mrz_birth:
            yy, mm, dd = int(mrz_birth[:2]), int(mrz_birth[2:4]), int(mrz_birth[4:6])
            year = 1900 + yy if yy > today.year % 100 else 2000 + yy
            birth = datetime(year, mm, dd).date()
            if birth > today:
                report.add(FraudFlag.DATE_INCONSISTENT, "naissance dans le futur")
                report.risk_score += 0.25
        if mrz_expiry:
            yy, mm, dd = int(mrz_expiry[:2]), int(mrz_expiry[2:4]), int(mrz_expiry[4:6])
            year = 2000 + yy   # passeports en cours: convention 2000+
            expiry = datetime(year, mm, dd).date()
            if expiry < today:
                report.add(FraudFlag.EXPIRED_DOCUMENT, f"expiré le {expiry}")
                report.risk_score += 0.20
    except (ValueError, IndexError):
        pass


# ============================================================
# Point d'entrée
# ============================================================

def detect_document_fraud(
    document_img: np.ndarray,
    declared_type: Optional[str] = None,
    detected_type: Optional[str] = None,
    mrz_checks_passed: Optional[bool] = None,
    mrz_birth: Optional[str] = None,
    mrz_expiry: Optional[str] = None,
    doc_has_face: Optional[bool] = None,
) -> FraudReport:
    report = FraudReport()

    if document_img is None or document_img.size == 0:
        report.add(FraudFlag.LOW_RESOLUTION, "image vide")
        report.risk_score = 1.0
        return report

    _resolution_check(document_img, report)
    _blur_check(document_img, report)
    _screen_capture_check(document_img, report)
    _ela_check(document_img, report)

    if mrz_checks_passed is False:
        report.add(FraudFlag.MRZ_CHECKSUM_FAIL, "checksum invalide")
        report.risk_score += 0.40

    if declared_type and detected_type and declared_type != detected_type:
        report.add(FraudFlag.DOC_MISMATCH,
                   f"déclaré={declared_type}, détecté={detected_type}")
        report.risk_score += 0.30

    if doc_has_face is False:
        report.add(FraudFlag.NO_FACE_ON_DOCUMENT, "")
        report.risk_score += 0.35

    _date_checks(mrz_birth, mrz_expiry, report)

    report.risk_score = float(min(1.0, report.risk_score))
    return report
