"""Modèles légers (dataclasses) — pas de dépendance Pydantic."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(slots=True)
class Match:
    identity_id: str
    full_name:   str
    role:        str
    similarity:  float


@dataclass(slots=True)
class RecognizeResponse:
    success:        bool
    event_type:     str
    face_count:     int
    matches:        list[Match] = field(default_factory=list)
    unknown_id:     Optional[str] = None
    is_live:        bool = True
    liveness_score: float = 1.0
    quality_score:  float = 0.0
    processing_ms:  float = 0.0
    event_id:       Optional[str] = None
    error:          Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "RecognizeResponse":
        matches = [Match(**m) for m in d.get("matches", [])]
        return cls(
            success=bool(d.get("success", False)),
            event_type=str(d.get("event_type", "")),
            face_count=int(d.get("face_count", 0)),
            matches=matches,
            unknown_id=d.get("unknown_id"),
            is_live=bool(d.get("is_live", True)),
            liveness_score=float(d.get("liveness_score", 1.0)),
            quality_score=float(d.get("quality_score", 0.0)),
            processing_ms=float(d.get("processing_ms", 0.0)),
            event_id=d.get("event_id"),
            error=d.get("error"),
        )


@dataclass(slots=True)
class AccessCheckResponse:
    decision:       str
    reason:         str
    identity_id:    Optional[str]
    identity_name:  Optional[str]
    similarity:     Optional[float]
    liveness_score: Optional[float]
    matched_policy: Optional[str]
    zone:           str
    access_point:   str
    event_id:       Optional[str]
    access_log_id:  Optional[str]
    processing_ms:  float

    @classmethod
    def from_dict(cls, d: dict) -> "AccessCheckResponse":
        return cls(**{k: d.get(k) for k in cls.__dataclass_fields__})  # type: ignore


@dataclass(slots=True)
class KYCResponse:
    session_id:        str
    decision:          str
    confidence:        float
    face_match_score:  Optional[float]
    liveness_score:    Optional[float]
    risk_score:        Optional[float]
    classified_type:   Optional[str]
    declared_type:     Optional[str]
    fraud_flags:       list[str]
    reasons:           list[str]

    @classmethod
    def from_dict(cls, d: dict) -> "KYCResponse":
        return cls(
            session_id=d.get("session_id", ""),
            decision=d.get("decision", "pending"),
            confidence=float(d.get("confidence", 0.0)),
            face_match_score=d.get("face_match_score"),
            liveness_score=d.get("liveness_score"),
            risk_score=d.get("risk_score"),
            classified_type=d.get("classified_type"),
            declared_type=d.get("declared_type"),
            fraud_flags=list(d.get("fraud_flags") or []),
            reasons=list(d.get("reasons") or []),
        )
