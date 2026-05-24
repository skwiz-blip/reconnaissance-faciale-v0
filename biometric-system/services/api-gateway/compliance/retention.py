"""
Politiques de rétention — purge périodique des données vieilles.

Configuration:
  - recognition_events : 90 jours
  - access_logs        : 180 jours
  - unknown_faces non résolus : 30 jours
  - liveness_challenges expirés : 7 jours
  - audit_logs : 730 jours (légal: 2 ans typique)
  - kyc_sessions rejected : 30 jours / approved : 5 ans (KYC AML)

À déclencher via la tâche Celery `tasks.retention_pass` (planifiée beat).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from loguru import logger

from database.supabase_client import get_supabase


@dataclass(slots=True)
class RetentionPolicy:
    table:          str
    days:           int
    where:          dict = field(default_factory=dict)   # filtres supplémentaires
    date_column:    str = "created_at"
    action:         str = "delete"                       # delete | anonymize


def default_policies() -> list[RetentionPolicy]:
    return [
        RetentionPolicy("recognition_events",  90,  date_column="created_at"),
        RetentionPolicy("access_logs",         180, date_column="created_at"),
        RetentionPolicy("unknown_faces",       30,  where={"resolved": False},
                                                    date_column="last_seen_at"),
        RetentionPolicy("liveness_challenges", 7,   where={"status": "expired"},
                                                    date_column="expires_at"),
        RetentionPolicy("audit_logs",          730, date_column="created_at"),
        # KYC rejected: garde 30 jours seulement
        RetentionPolicy("kyc_sessions",        30,  where={"decision": "rejected"},
                                                    date_column="created_at"),
    ]


@dataclass(slots=True)
class RetentionResult:
    table:    str
    deleted:  int
    cutoff:   str


async def run_retention_pass(policies: list[RetentionPolicy] | None = None) -> list[RetentionResult]:
    """Applique toutes les politiques. Idempotent (rerun-safe)."""
    sb = get_supabase()
    results: list[RetentionResult] = []
    for p in policies or default_policies():
        cutoff = (datetime.now(timezone.utc) - timedelta(days=p.days)).isoformat()
        q = sb.table(p.table).delete().lt(p.date_column, cutoff)
        for k, v in p.where.items():
            q = q.eq(k, v)
        try:
            res = q.execute()
            n = len(res.data or [])
            results.append(RetentionResult(p.table, n, cutoff))
            logger.info(f"Retention: {p.table} → {n} lignes supprimées (< {cutoff})")
        except Exception as e:
            logger.warning(f"Retention {p.table}: {e}")
            results.append(RetentionResult(p.table, 0, cutoff))
    return results
