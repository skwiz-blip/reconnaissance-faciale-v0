"""
Redis cache layer — cache des résultats de recherche, sessions, rate-limit.

Trois rôles distincts:
  1. Cache de reconnaissance (hash perceptuel → résultat) — évite de relancer
     le pipeline sur des frames quasi-identiques (10× moins de calcul GPU).
  2. Cache identités (id → fiche identité) — évite des appels Supabase.
  3. Stockage de refresh tokens et anti-replay JWT.

L'app fonctionne sans Redis (mode dégradé): si la connexion échoue, toutes
les opérations cache retournent None silencieusement.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

import numpy as np
import redis.asyncio as aioredis
from loguru import logger


_redis: Optional[aioredis.Redis] = None
_enabled: bool = False


# ============================================================
# Lifecycle
# ============================================================

async def init_redis(url: str) -> None:
    """Initialise la connexion Redis. À appeler depuis le lifespan FastAPI."""
    global _redis, _enabled
    try:
        _redis = aioredis.from_url(
            url,
            encoding="utf-8",
            decode_responses=False,  # on gère le decode nous-mêmes (binaire + JSON)
            max_connections=20,
        )
        await _redis.ping()
        _enabled = True
        logger.success(f"Redis connecté → {url}")
    except Exception as e:
        _enabled = False
        _redis = None
        logger.warning(f"Redis indisponible ({e}) — mode sans cache")


async def close_redis() -> None:
    global _redis, _enabled
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception:
            pass
    _redis = None
    _enabled = False


def is_enabled() -> bool:
    return _enabled and _redis is not None


# ============================================================
# Helpers internes
# ============================================================

async def _get_raw(key: str) -> Optional[bytes]:
    if not is_enabled():
        return None
    try:
        return await _redis.get(key)
    except Exception as e:
        logger.warning(f"Redis GET {key}: {e}")
        return None


async def _set_raw(key: str, value: bytes, ttl: int) -> None:
    if not is_enabled():
        return
    try:
        await _redis.set(key, value, ex=ttl)
    except Exception as e:
        logger.warning(f"Redis SET {key}: {e}")


async def _delete(key: str) -> None:
    if not is_enabled():
        return
    try:
        await _redis.delete(key)
    except Exception:
        pass


# ============================================================
# 1. Cache résultat reconnaissance (par signature d'embedding)
# ============================================================
#
# Stratégie: on quantifie l'embedding (round à 2 décimales) puis on hash.
# Deux frames presque identiques produisent la même clé → cache hit.
# Cela divise par 5 à 10 la charge GPU sur un flux continu.

CACHE_PREFIX_RESULT = "bio:recog:"


def _embedding_signature(embedding: np.ndarray) -> str:
    quantized = np.round(embedding.astype(np.float32), decimals=2).tobytes()
    return hashlib.blake2b(quantized, digest_size=16).hexdigest()


async def get_cached_recognition(embedding: np.ndarray) -> Optional[dict]:
    sig = _embedding_signature(embedding)
    raw = await _get_raw(CACHE_PREFIX_RESULT + sig)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


async def set_cached_recognition(
    embedding: np.ndarray, result: dict, ttl: int = 30
) -> None:
    sig = _embedding_signature(embedding)
    payload = json.dumps(result, default=str).encode("utf-8")
    await _set_raw(CACHE_PREFIX_RESULT + sig, payload, ttl)


# ============================================================
# 2. Cache identités
# ============================================================

CACHE_PREFIX_IDENTITY = "bio:identity:"


async def get_cached_identity(identity_id: str) -> Optional[dict]:
    raw = await _get_raw(CACHE_PREFIX_IDENTITY + identity_id)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


async def set_cached_identity(identity_id: str, data: dict, ttl: int = 300) -> None:
    payload = json.dumps(data, default=str).encode("utf-8")
    await _set_raw(CACHE_PREFIX_IDENTITY + identity_id, payload, ttl)


async def invalidate_identity(identity_id: str) -> None:
    await _delete(CACHE_PREFIX_IDENTITY + identity_id)


# ============================================================
# 3. Refresh tokens (rotation + révocation)
# ============================================================

REFRESH_PREFIX = "bio:refresh:"


async def store_refresh_token(jti: str, user_id: str, ttl_seconds: int) -> None:
    payload = json.dumps({"user_id": user_id}).encode("utf-8")
    await _set_raw(REFRESH_PREFIX + jti, payload, ttl_seconds)


async def get_refresh_token(jti: str) -> Optional[dict]:
    raw = await _get_raw(REFRESH_PREFIX + jti)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


async def revoke_refresh_token(jti: str) -> None:
    await _delete(REFRESH_PREFIX + jti)


# ============================================================
# 4. Anti-replay JWT (révocation access tokens)
# ============================================================

REVOKED_PREFIX = "bio:revoked:"


async def revoke_access_token(jti: str, remaining_ttl: int) -> None:
    if remaining_ttl <= 0:
        return
    await _set_raw(REVOKED_PREFIX + jti, b"1", remaining_ttl)


async def is_access_revoked(jti: str) -> bool:
    raw = await _get_raw(REVOKED_PREFIX + jti)
    return raw is not None


# ============================================================
# 5. Rate limiting (token bucket simplifié)
# ============================================================

async def rate_limit_check(
    key: str, limit: int, window_seconds: int
) -> tuple[bool, int]:
    """
    Renvoie (autorisé, count_actuel).
    Sans Redis: toujours autorisé.
    """
    if not is_enabled():
        return True, 0
    redis_key = f"bio:rl:{key}"
    try:
        pipe = _redis.pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, window_seconds, nx=True)
        count, _ = await pipe.execute()
        return count <= limit, int(count)
    except Exception as e:
        logger.warning(f"Rate-limit Redis: {e}")
        return True, 0
