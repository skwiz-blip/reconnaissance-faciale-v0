"""
Tâches Celery — exécution asynchrone et planifiée.

Lancée par le worker docker-compose:
    celery -A tasks worker --loglevel=info --concurrency=2

Tâches:
  - run_clustering: clustering DBSCAN périodique sur les inconnus
  - log_audit: log d'audit asynchrone
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../ai-core"))

import asyncio

from celery import Celery
from celery.schedules import crontab
from loguru import logger

from config import get_settings


settings = get_settings()

celery_app = Celery(
    "biometric_tasks",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=600,
)


# ============================================================
# Schedule (Celery Beat)
# ============================================================

celery_app.conf.beat_schedule = {
    "cluster-unknowns-hourly": {
        "task": "tasks.cluster_unknowns_task",
        "schedule": crontab(minute=5),  # toutes les heures à HH:05
    },
    "retention-daily": {
        "task": "tasks.retention_pass_task",
        "schedule": crontab(hour=3, minute=0),  # 03:00 UTC quotidien
    },
}


# ============================================================
# Tâches
# ============================================================

@celery_app.task(name="tasks.cluster_unknowns_task")
def cluster_unknowns_task(
    similarity_threshold: float = 0.65,
    min_samples: int = 2,
) -> dict:
    """Lance une passe de clustering DBSCAN sur les inconnus non résolus."""
    from clustering import run_clustering_pass

    result = asyncio.run(
        run_clustering_pass(
            similarity_threshold=similarity_threshold,
            min_samples=min_samples,
        )
    )
    logger.info(
        f"Clustering périodique: {result.n_clusters} clusters, "
        f"{result.n_noise} bruit, {result.n_processed} traités"
    )
    return {
        "n_clusters":  result.n_clusters,
        "n_noise":     result.n_noise,
        "n_processed": result.n_processed,
    }


@celery_app.task(name="tasks.log_audit")
def log_audit_task(payload: dict) -> None:
    """Écrit un événement dans audit_logs (non bloquant pour l'API)."""
    from database.supabase_client import get_supabase
    try:
        get_supabase().table("audit_logs").insert(payload).execute()
    except Exception as e:
        logger.warning(f"Audit log écriture échouée: {e}")


@celery_app.task(name="tasks.retention_pass_task")
def retention_pass_task() -> dict:
    """Purge les données vieilles selon les RetentionPolicy par défaut."""
    from compliance.retention import run_retention_pass
    from database.supabase_client import get_supabase

    results = asyncio.run(run_retention_pass())
    sb = get_supabase()
    for r in results:
        try:
            sb.table("retention_runs").insert({
                "table_name":    r.table,
                "cutoff":        r.cutoff,
                "deleted_count": r.deleted,
                "triggered_by":  "celery_beat",
            }).execute()
        except Exception as e:
            logger.warning(f"Persist retention_run {r.table}: {e}")

    total = sum(r.deleted for r in results)
    logger.info(f"Retention quotidienne: {total} lignes supprimées sur {len(results)} tables")
    return {"total_deleted": total, "tables": [r.table for r in results]}
