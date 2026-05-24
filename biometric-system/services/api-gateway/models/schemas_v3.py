"""Schémas Pydantic Phase 3 — KYC, accès, zones, liveness challenges."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ============================================================
# LIVENESS CHALLENGES
# ============================================================

class ChallengeActionEnum(str, Enum):
    blink       = "blink"
    turn_left   = "turn_left"
    turn_right  = "turn_right"
    look_up     = "look_up"
    look_down   = "look_down"
    smile       = "smile"
    open_mouth  = "open_mouth"


class ChallengeStatusEnum(str, Enum):
    pending = "pending"
    passed  = "passed"
    failed  = "failed"
    expired = "expired"


class IssueChallengeRequest(BaseModel):
    action:     Optional[ChallengeActionEnum] = None
    issued_for: str = Field(default="login", max_length=32)
    identity_id: Optional[str] = None


class ChallengeStatusResponse(BaseModel):
    challenge_id: str
    action:       ChallengeActionEnum
    status:       ChallengeStatusEnum
    progress:     float
    expires_at:   datetime
    started_at:   datetime
    issued_for:   Optional[str] = None


class SubmitChallengeFrameRequest(BaseModel):
    challenge_id: str
    image_base64: str = Field(..., description="Frame courante en base64")


# ============================================================
# ZONES & POLITIQUES
# ============================================================

class SecurityLevel(str, Enum):
    public      = "public"
    restricted  = "restricted"
    secured     = "secured"
    classified  = "classified"


class ZoneCreate(BaseModel):
    code:           str = Field(..., min_length=2, max_length=64, pattern=r"^[a-z0-9_\-]+$")
    name:           str = Field(..., min_length=2, max_length=120)
    description:    Optional[str] = None
    security_level: SecurityLevel = SecurityLevel.public
    metadata:       Optional[dict] = None


class ZoneUpdate(BaseModel):
    name:           Optional[str] = None
    description:    Optional[str] = None
    security_level: Optional[SecurityLevel] = None
    is_active:      Optional[bool] = None
    metadata:       Optional[dict] = None


class ZoneResponse(BaseModel):
    id:             str
    code:           str
    name:           str
    description:    Optional[str]
    security_level: str
    is_active:      bool
    created_at:     datetime


class AccessPolicyCreate(BaseModel):
    zone_id:                 str
    name:                    str = Field(..., min_length=2, max_length=120)
    priority:                int = Field(100, ge=0, le=1000)
    allowed_roles:           list[str] = Field(..., min_length=1)
    allowed_days:            Optional[list[str]] = None
    start_time:              Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")
    end_time:                Optional[str] = Field(None, pattern=r"^\d{2}:\d{2}$")
    require_liveness:        bool = False
    min_similarity:          Optional[float] = Field(None, ge=0.0, le=1.0)
    alert_below_similarity:  Optional[float] = Field(None, ge=0.0, le=1.0)
    max_per_minute:          Optional[int] = Field(None, ge=1, le=120)


class AccessPolicyResponse(AccessPolicyCreate):
    id:        str
    is_active: bool
    created_at: datetime


# ============================================================
# CONTRÔLE D'ACCÈS (vérification temps réel)
# ============================================================

class AccessCheckRequest(BaseModel):
    """Vérification d'accès depuis une image (caméra de porte)."""
    image_base64:   str
    zone_code:      str = Field(..., min_length=2)
    access_point:   str = Field(..., min_length=2)
    camera_id:      Optional[str] = None
    check_liveness: bool = True


class AccessCheckResponse(BaseModel):
    decision:        str                     # granted | denied | alert
    reason:          str
    identity_id:     Optional[str]
    identity_name:   Optional[str]
    similarity:      Optional[float]
    liveness_score:  Optional[float]
    matched_policy:  Optional[str]
    zone:            str
    access_point:    str
    event_id:        Optional[str] = None
    access_log_id:   Optional[str] = None
    processing_ms:   float


# ============================================================
# KYC
# ============================================================

class KYCDocTypeEnum(str, Enum):
    passport         = "passport"
    id_card          = "id_card"
    driver_license   = "driver_license"
    residence_permit = "residence_permit"


class KYCStartRequest(BaseModel):
    identity_id:  Optional[str] = None
    doc_type:     KYCDocTypeEnum
    issue_challenge: bool = True


class KYCStartResponse(BaseModel):
    session_id:    str
    session_token: str
    challenge:     Optional[ChallengeStatusResponse] = None


class KYCSubmitRequest(BaseModel):
    session_token:  str
    selfie_base64:  str
    document_base64: str


class KYCVerdictResponse(BaseModel):
    session_id:      str
    decision:        str            # approved | review | rejected
    confidence:      float
    face_match_score: Optional[float]
    liveness_score:   Optional[float]
    risk_score:       Optional[float]
    classified_type:  Optional[str]
    declared_type:    Optional[str]
    fraud_flags:      list[str]
    reasons:          list[str]
    mrz:              Optional[dict] = None
    ocr_fields:       Optional[dict] = None


# ============================================================
# AUDIT
# ============================================================

class AuditLogResponse(BaseModel):
    id:          str
    actor_id:    Optional[str]
    actor_role:  Optional[str]
    action:      str
    target_type: Optional[str]
    target_id:   Optional[str]
    ip_address:  Optional[str]
    user_agent:  Optional[str]
    metadata:    Optional[dict]
    created_at:  datetime
