"""
Policy engine — décide si une identité peut accéder à une zone.

Politique multi-couches (toutes doivent passer):
    1. Identité ACTIVE et non bloquée
    2. Zone existe et active
    3. Rôle autorisé (intersection rôles identité × rôles politique)
    4. Fenêtre horaire (jour de semaine + plage horaire)
    5. Liveness validée si la zone exige une preuve de vivacité
    6. Niveau de sécurité minimum (similarity score reco)
    7. Quota anti-tailgating (max N accès par minute par identité)

Décisions:
    GRANTED  : tout valide → ouverture autorisée
    DENIED   : règle bloquante (rôle, statut, horaire)
    ALERT    : score faible mais autorisé → notification supervisor
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timezone
from enum import Enum
from typing import Optional

from loguru import logger

from database import redis_cache
from database.supabase_client import get_supabase


class AccessDecision(str, Enum):
    GRANTED = "granted"
    DENIED  = "denied"
    ALERT   = "alert"


@dataclass(slots=True)
class AccessRequest:
    identity_id:     Optional[str]
    zone_code:       str
    access_point:    str
    similarity:      Optional[float] = None
    liveness_passed: Optional[bool] = None
    liveness_score:  Optional[float] = None
    at:              Optional[datetime] = None
    camera_id:       Optional[str] = None
    metadata:        dict = field(default_factory=dict)


@dataclass(slots=True)
class AccessResult:
    decision:        AccessDecision
    reason:          str
    matched_policy:  Optional[str] = None
    required_role:   Optional[list[str]] = None
    triggered_at:    datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ============================================================
# Helpers temps
# ============================================================

DAY_NAMES = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _day_code(dt: datetime) -> str:
    return DAY_NAMES[dt.weekday()]


def _in_time_window(now: datetime, window_start: Optional[str], window_end: Optional[str]) -> bool:
    """window_start/end au format 'HH:MM' (heure locale UTC)."""
    if not window_start and not window_end:
        return True
    try:
        h1, m1 = map(int, (window_start or "00:00").split(":"))
        h2, m2 = map(int, (window_end or "23:59").split(":"))
        ws = time(h1, m1)
        we = time(h2, m2)
        current = now.time()
        if ws <= we:
            return ws <= current <= we
        # Fenêtre traversant minuit
        return current >= ws or current <= we
    except (ValueError, AttributeError):
        return True


# ============================================================
# Fetch helpers (avec cache Redis 60s)
# ============================================================

ZONE_CACHE_PREFIX = "bio:zone:"
POLICY_CACHE_PREFIX = "bio:policies:"


async def _fetch_zone(zone_code: str) -> Optional[dict]:
    import json
    raw = await redis_cache._get_raw(ZONE_CACHE_PREFIX + zone_code)
    if raw is not None:
        try:
            return json.loads(raw)
        except Exception:
            pass
    sb = get_supabase()
    res = sb.table("zones").select("*").eq("code", zone_code).execute()
    if not res.data:
        return None
    zone = res.data[0]
    await redis_cache._set_raw(
        ZONE_CACHE_PREFIX + zone_code,
        json.dumps(zone, default=str).encode("utf-8"),
        ttl=60,
    )
    return zone


async def _fetch_policies(zone_id: str) -> list[dict]:
    import json
    raw = await redis_cache._get_raw(POLICY_CACHE_PREFIX + zone_id)
    if raw is not None:
        try:
            return json.loads(raw)
        except Exception:
            pass
    sb = get_supabase()
    res = (
        sb.table("access_policies")
        .select("*")
        .eq("zone_id", zone_id)
        .eq("is_active", True)
        .order("priority", desc=True)
        .execute()
    )
    policies = res.data or []
    await redis_cache._set_raw(
        POLICY_CACHE_PREFIX + zone_id,
        json.dumps(policies, default=str).encode("utf-8"),
        ttl=60,
    )
    return policies


async def _fetch_identity(identity_id: str) -> Optional[dict]:
    cached = await redis_cache.get_cached_identity(identity_id)
    if cached:
        return cached
    sb = get_supabase()
    res = sb.table("identities").select("id, full_name, role, status").eq("id", identity_id).execute()
    if not res.data:
        return None
    iden = res.data[0]
    await redis_cache.set_cached_identity(identity_id, iden, ttl=300)
    return iden


# ============================================================
# Anti-tailgating
# ============================================================

async def _check_rate_quota(identity_id: str, zone_code: str, max_per_minute: int) -> bool:
    key = f"access:{identity_id}:{zone_code}"
    ok, _ = await redis_cache.rate_limit_check(key, max_per_minute, window_seconds=60)
    return ok


# ============================================================
# Decision core
# ============================================================

async def evaluate_access(req: AccessRequest) -> AccessResult:
    now = req.at or datetime.now(timezone.utc)

    # 1. Identité
    if not req.identity_id:
        return AccessResult(AccessDecision.DENIED, "identité inconnue (visage non reconnu)")

    iden = await _fetch_identity(req.identity_id)
    if not iden:
        return AccessResult(AccessDecision.DENIED, "identité introuvable")
    if iden.get("status") != "active":
        return AccessResult(AccessDecision.DENIED, f"identité {iden.get('status')}")
    if iden.get("role") == "blocked":
        return AccessResult(AccessDecision.DENIED, "identité bloquée")

    # 2. Zone
    zone = await _fetch_zone(req.zone_code)
    if not zone:
        return AccessResult(AccessDecision.DENIED, f"zone inconnue: {req.zone_code}")
    if not zone.get("is_active", True):
        return AccessResult(AccessDecision.DENIED, "zone désactivée")

    # 3. Policies
    policies = await _fetch_policies(zone["id"])
    if not policies:
        return AccessResult(
            AccessDecision.DENIED,
            f"aucune politique active pour zone {req.zone_code}",
        )

    # 4. Évaluation séquentielle des politiques (priorité décroissante)
    for p in policies:
        allowed_roles = p.get("allowed_roles") or []
        if allowed_roles and iden["role"] not in allowed_roles:
            continue  # politique suivante

        days = p.get("allowed_days") or []
        if days and _day_code(now) not in days:
            continue

        if not _in_time_window(now, p.get("start_time"), p.get("end_time")):
            continue

        # Vérifications de sécurité
        if p.get("require_liveness") and not req.liveness_passed:
            return AccessResult(
                AccessDecision.DENIED,
                f"liveness requise pour la politique '{p['name']}'",
                matched_policy=p["name"],
            )

        min_sim = p.get("min_similarity")
        if min_sim and (req.similarity is None or req.similarity < min_sim):
            return AccessResult(
                AccessDecision.DENIED,
                f"similarité {req.similarity} < min {min_sim} ({p['name']})",
                matched_policy=p["name"],
            )

        max_per_min = p.get("max_per_minute")
        if max_per_min and not await _check_rate_quota(req.identity_id, req.zone_code, max_per_min):
            return AccessResult(
                AccessDecision.DENIED,
                f"quota dépassé ({max_per_min}/min) sur {req.zone_code}",
                matched_policy=p["name"],
            )

        # Décision: granted ou alert si liveness faible
        alert_threshold = p.get("alert_below_similarity")
        if alert_threshold and req.similarity is not None and req.similarity < alert_threshold:
            return AccessResult(
                AccessDecision.ALERT,
                f"accès accordé mais score faible ({req.similarity:.2f}) — supervisor notifié",
                matched_policy=p["name"],
                required_role=allowed_roles,
            )

        return AccessResult(
            AccessDecision.GRANTED,
            f"politique '{p['name']}' validée",
            matched_policy=p["name"],
            required_role=allowed_roles,
        )

    return AccessResult(
        AccessDecision.DENIED,
        f"aucune politique ne correspond (rôle={iden['role']}, jour={_day_code(now)})",
    )


async def evaluate_access_for_identity(
    identity_id: Optional[str],
    zone_code: str,
    access_point: str,
    similarity: Optional[float] = None,
    liveness_passed: Optional[bool] = None,
    liveness_score: Optional[float] = None,
    camera_id: Optional[str] = None,
) -> AccessResult:
    """Helper compact pour appel depuis un endpoint."""
    return await evaluate_access(AccessRequest(
        identity_id=identity_id,
        zone_code=zone_code,
        access_point=access_point,
        similarity=similarity,
        liveness_passed=liveness_passed,
        liveness_score=liveness_score,
        camera_id=camera_id,
    ))


# ============================================================
# Invalidation cache (à appeler après mutations)
# ============================================================

async def invalidate_zone_cache(zone_code: str, zone_id: Optional[str] = None) -> None:
    await redis_cache._delete(ZONE_CACHE_PREFIX + zone_code)
    if zone_id:
        await redis_cache._delete(POLICY_CACHE_PREFIX + zone_id)
