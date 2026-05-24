"""
Création / décodage des JWT (access + refresh).

Stratégie:
  - Access token: courte durée (15min par défaut), porté en Authorization Bearer.
  - Refresh token: longue durée (30j), JTI stocké côté Redis pour rotation.
  - Chaque token a un jti unique → permet révocation fine.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from jose import JWTError, jwt
from loguru import logger

from config import get_settings


TokenType = Literal["access", "refresh"]
ALGORITHM = "HS256"


@dataclass(slots=True)
class TokenPayload:
    sub: str               # user_id
    role: str
    type: TokenType
    jti: str
    exp: int               # unix seconds
    iat: int


# ============================================================
# Création
# ============================================================

def _create_token(
    user_id: str,
    role: str,
    token_type: TokenType,
    ttl_minutes: int,
) -> tuple[str, str, int]:
    """
    Retourne (jwt_string, jti, expires_at_unix).
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=ttl_minutes)
    jti = uuid.uuid4().hex

    payload = {
        "sub":  user_id,
        "role": role,
        "type": token_type,
        "jti":  jti,
        "iat":  int(now.timestamp()),
        "exp":  int(exp.timestamp()),
        "iss":  "biometric-api",
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
    return token, jti, int(exp.timestamp())


def create_access_token(user_id: str, role: str) -> tuple[str, str, int]:
    settings = get_settings()
    return _create_token(user_id, role, "access", settings.jwt_expire_minutes)


def create_refresh_token(user_id: str, role: str) -> tuple[str, str, int]:
    settings = get_settings()
    return _create_token(user_id, role, "refresh", settings.refresh_token_expire_minutes)


# ============================================================
# Décodage
# ============================================================

def decode_token(token: str, expected_type: Optional[TokenType] = None) -> TokenPayload:
    """
    Décode et valide signature + expiration.
    Lève JWTError si invalide ou si le type ne correspond pas.
    """
    settings = get_settings()
    try:
        data = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError as e:
        logger.debug(f"JWT decode échec: {e}")
        raise

    if expected_type and data.get("type") != expected_type:
        raise JWTError(f"Type de token attendu: {expected_type}, reçu: {data.get('type')}")

    return TokenPayload(
        sub=data["sub"],
        role=data.get("role", "user"),
        type=data["type"],
        jti=data["jti"],
        exp=int(data["exp"]),
        iat=int(data["iat"]),
    )
