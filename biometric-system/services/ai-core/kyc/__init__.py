"""KYC (Know Your Customer) — vérification biométrique d'identité.

Pipeline:
    document → classifier → OCR/MRZ → extraction → face match selfie ↔ doc → fraud detection → verdict
"""
from kyc.document_classifier import DocumentType, DocumentClassifier, classify_document
from kyc.ocr import OCRResult, OCREngine, extract_text
from kyc.mrz import MRZData, parse_mrz, MRZParseError
from kyc.face_match import FaceMatchResult, compare_selfie_to_document
from kyc.fraud_detection import FraudReport, detect_document_fraud
from kyc.pipeline import KYCPipeline, KYCVerdict, get_kyc_pipeline

__all__ = [
    "DocumentType", "DocumentClassifier", "classify_document",
    "OCRResult", "OCREngine", "extract_text",
    "MRZData", "parse_mrz", "MRZParseError",
    "FaceMatchResult", "compare_selfie_to_document",
    "FraudReport", "detect_document_fraud",
    "KYCPipeline", "KYCVerdict", "get_kyc_pipeline",
]
