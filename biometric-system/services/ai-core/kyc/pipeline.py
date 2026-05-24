"""
Pipeline KYC complet — orchestre toutes les vérifications.

Étapes:
    1. Classification du document
    2. OCR + extraction de champs
    3. Parsing MRZ si présente
    4. Face matching selfie ↔ document
    5. Liveness sur selfie
    6. Détection de fraude
    7. Verdict final + score consolidé

Décision:
    APPROVED  : face match OK + liveness OK + risk_score < 0.3 + tous checks MRZ
    REVIEW    : face match OK mais flags mineurs OU score moyen
    REJECTED  : face match KO ou flags critiques
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

import cv2
import numpy as np
from loguru import logger

from kyc.document_classifier import classify_document, DocumentType, DocumentClassification
from kyc.face_match import compare_selfie_to_document, FaceMatchResult, KYC_DEFAULT_THRESHOLD
from kyc.fraud_detection import detect_document_fraud, FraudReport, FraudFlag
from kyc.mrz import parse_mrz, MRZData, MRZParseError
from kyc.ocr import extract_text, OCRResult


class KYCDecision(str, Enum):
    APPROVED = "approved"
    REVIEW   = "review"
    REJECTED = "rejected"


@dataclass(slots=True)
class KYCVerdict:
    decision:       KYCDecision
    confidence:     float
    face_match:     Optional[FaceMatchResult] = None
    liveness_passed: bool = False
    liveness_score: float = 0.0
    fraud:          Optional[FraudReport] = None
    classification: Optional[DocumentClassification] = None
    ocr:            Optional[OCRResult] = None
    mrz:            Optional[MRZData] = None
    reasons:        list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = {
            "decision":        self.decision.value,
            "confidence":      round(self.confidence, 3),
            "liveness_passed": self.liveness_passed,
            "liveness_score":  round(self.liveness_score, 3),
            "reasons":         self.reasons,
        }
        if self.face_match:
            d["face_match"] = {
                "is_match":   self.face_match.is_match,
                "similarity": self.face_match.similarity,
                "threshold":  self.face_match.threshold_used,
                "reason":     self.face_match.reason,
            }
        if self.fraud:
            d["fraud"] = self.fraud.as_dict()
        if self.classification:
            d["classification"] = {
                "doc_type":   self.classification.doc_type.value,
                "confidence": self.classification.confidence,
                "has_mrz":    self.classification.has_mrz,
                "notes":      self.classification.notes,
            }
        if self.ocr:
            d["ocr"] = {
                "engine":     self.ocr.engine,
                "confidence": self.ocr.confidence,
                "fields":     self.ocr.fields,
            }
        if self.mrz:
            d["mrz"] = {
                "document_type":   self.mrz.document_type,
                "issuing_country": self.mrz.issuing_country,
                "surname":         self.mrz.surname,
                "given_names":     self.mrz.given_names,
                "document_number": self.mrz.document_number,
                "nationality":     self.mrz.nationality,
                "birth_date":      self.mrz.birth_date,
                "sex":             self.mrz.sex,
                "expiry_date":     self.mrz.expiry_date,
                "checks_passed":   self.mrz.checks_passed,
            }
        return d


class KYCPipeline:
    def __init__(
        self,
        face_match_threshold: float = KYC_DEFAULT_THRESHOLD,
        liveness_threshold: float = 0.55,
        ocr_lang: str = "fra+eng",
    ):
        self.face_match_threshold = face_match_threshold
        self.liveness_threshold = liveness_threshold
        self.ocr_lang = ocr_lang

    def verify(
        self,
        selfie_img: np.ndarray,
        document_img: np.ndarray,
        declared_doc_type: Optional[str] = None,
        run_ocr: bool = True,
    ) -> KYCVerdict:
        verdict = KYCVerdict(decision=KYCDecision.REJECTED, confidence=0.0)

        # 1. Classification
        cls = classify_document(document_img)
        verdict.classification = cls

        # 2. OCR + MRZ
        ocr_result: Optional[OCRResult] = None
        mrz: Optional[MRZData] = None
        if run_ocr:
            try:
                ocr_result = extract_text(document_img, lang=self.ocr_lang)
                verdict.ocr = ocr_result
                if cls.has_mrz and ocr_result.full_text:
                    try:
                        mrz = parse_mrz(ocr_result.full_text)
                        verdict.mrz = mrz
                    except MRZParseError as e:
                        logger.debug(f"MRZ parse: {e}")
            except Exception as e:
                logger.warning(f"OCR/MRZ pipeline: {e}")

        # 3. Face match
        face_match = compare_selfie_to_document(
            selfie_img, document_img, threshold=self.face_match_threshold
        )
        verdict.face_match = face_match

        # 4. Liveness sur le selfie
        liveness_passed = False
        liveness_score = 0.0
        try:
            from liveness_v2 import get_liveness_v2
            from detector import get_detector
            faces = get_detector().detect(selfie_img)
            if faces:
                lv = get_liveness_v2().analyze(faces[0].face_img, faces[0].landmarks)
                liveness_score = lv.score
                liveness_passed = lv.is_live
        except Exception as e:
            logger.warning(f"Liveness KYC: {e}")
        verdict.liveness_score = liveness_score
        verdict.liveness_passed = liveness_passed

        # 5. Fraud detection
        fraud = detect_document_fraud(
            document_img,
            declared_type=declared_doc_type,
            detected_type=cls.doc_type.value if cls.doc_type != DocumentType.UNKNOWN else None,
            mrz_checks_passed=mrz.all_checks_ok if mrz else None,
            mrz_birth=mrz.birth_date if mrz else None,
            mrz_expiry=mrz.expiry_date if mrz else None,
            doc_has_face=face_match.doc_face_count > 0,
        )
        verdict.fraud = fraud

        # 6. Verdict
        verdict.decision, verdict.confidence, verdict.reasons = self._decide(
            face_match, liveness_passed, liveness_score, fraud, mrz
        )
        return verdict

    def _decide(
        self,
        face_match: FaceMatchResult,
        liveness_passed: bool,
        liveness_score: float,
        fraud: FraudReport,
        mrz: Optional[MRZData],
    ) -> tuple[KYCDecision, float, list[str]]:
        reasons: list[str] = []
        critical_flags = {
            FraudFlag.EDITED_REGION,
            FraudFlag.MRZ_CHECKSUM_FAIL,
            FraudFlag.SCREEN_CAPTURE,
        }
        critical_present = any(f in fraud.flags for f in critical_flags)

        if not face_match.is_match:
            reasons.append(f"face_match KO: {face_match.reason}")
            return KYCDecision.REJECTED, max(0.0, face_match.similarity), reasons

        if not liveness_passed:
            reasons.append(f"liveness KO (score={liveness_score:.2f})")
            return KYCDecision.REJECTED, 0.4, reasons

        if critical_present:
            reasons.append(f"fraude critique: {[f.value for f in fraud.flags if f in critical_flags]}")
            return KYCDecision.REJECTED, 0.3, reasons

        # Score consolidé: face_match (50%) + liveness (25%) + (1-fraud_risk) (25%)
        consolidated = (
            0.5 * face_match.similarity
            + 0.25 * liveness_score
            + 0.25 * (1.0 - fraud.risk_score)
        )

        if fraud.risk_score < 0.20 and (mrz is None or mrz.all_checks_ok):
            return KYCDecision.APPROVED, round(consolidated, 3), reasons or ["all checks passed"]

        if fraud.risk_score < 0.50:
            reasons.append(f"risk_score modéré: {fraud.risk_score:.2f}")
            return KYCDecision.REVIEW, round(consolidated, 3), reasons

        reasons.append(f"risk_score élevé: {fraud.risk_score:.2f}")
        return KYCDecision.REJECTED, round(consolidated, 3), reasons


_pipeline: Optional[KYCPipeline] = None


def get_kyc_pipeline() -> KYCPipeline:
    global _pipeline
    if _pipeline is None:
        from config import get_settings
        s = get_settings()
        _pipeline = KYCPipeline(
            face_match_threshold=s.kyc_face_match_threshold,
            liveness_threshold=s.liveness_threshold,
            ocr_lang=s.ocr_languages,
        )
    return _pipeline
