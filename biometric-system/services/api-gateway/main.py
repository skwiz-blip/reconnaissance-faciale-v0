"""
BIOMETRIC SYSTEM — Point d'entrée FastAPI
Démarre avec: uvicorn main:app --reload --host 0.0.0.0 --port 8000
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../ai-core"))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from loguru import logger
import time

from config import get_settings
from database import faiss_index, redis_cache
from routers.recognize import router as recognize_router
from routers.identity import router as identity_router, unknowns_router
from routers.websocket import router as ws_router
from routers.auth import router as auth_router
from routers.clusters import router as clusters_router
from routers.kyc import router as kyc_router
from routers.liveness import router as liveness_router
from routers.access import router as access_router
from routers.audit import router as audit_router
from routers.compliance import router as compliance_router
from routers.tenants import router as tenants_router
from routers.voice import router as voice_router
from routers.affect import router as affect_router
from routers.webhooks import router as webhooks_router
from routers.learning import router as learning_router

settings = get_settings()


# ============================================================
# LIFESPAN — initialisation au démarrage
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Démarrage Biometric System API...")

    # 1. Pipeline IA (charge les modèles ONNX en mémoire)
    try:
        from pipeline import get_pipeline
        get_pipeline()
        logger.success("Pipeline IA initialisé")
    except Exception as e:
        logger.warning(f"Pipeline init: {e}")

    # 2. Supabase (connexion + sanity check)
    try:
        from database.supabase_client import get_supabase
        get_supabase().table("cameras").select("id").limit(1).execute()
        logger.success("Supabase connecté")
    except Exception as e:
        logger.warning(f"Supabase connexion: {e}")

    # 3. Redis (cache + sessions) — optionnel
    await redis_cache.init_redis(settings.redis_url)

    # 4. FAISS index (chargement complet depuis Supabase + resync périodique)
    try:
        await faiss_index.start_faiss(resync_interval_s=settings.faiss_resync_interval_s)
    except Exception as e:
        logger.warning(f"FAISS init: {e}")

    logger.success(f"API prête sur http://{settings.app_host}:{settings.app_port}")
    yield

    logger.info("Arrêt de l'API...")
    await faiss_index.stop_faiss()
    await redis_cache.close_redis()


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Biometric Recognition System",
    description=(
        "API professionnelle de reconnaissance faciale biométrique.\n\n"
        "**Phase 2** — FAISS, Redis cache, JWT auth, clustering DBSCAN, WebSocket sécurisé.\n\n"
        "Auth: POST /api/v1/auth/login pour obtenir un Bearer token, "
        "puis `Authorization: Bearer <token>` sur les endpoints protégés."
    ),
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# ============================================================
# MIDDLEWARE
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

from middleware.audit import AuditMiddleware
app.add_middleware(AuditMiddleware)

# Multi-tenant (Phase 6) — pose le tenant context au début de chaque requête
from tenancy import TenantMiddleware
app.add_middleware(TenantMiddleware)

if settings.metrics_enabled:
    from observability.metrics import PrometheusMiddleware
    app.add_middleware(PrometheusMiddleware)


@app.middleware("http")
async def add_timing_header(request: Request, call_next):
    t0 = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Process-Time"] = f"{(time.perf_counter() - t0) * 1000:.1f}ms"
    return response


# ============================================================
# ROUTES
# ============================================================

app.include_router(auth_router)
app.include_router(recognize_router)
app.include_router(identity_router)
app.include_router(unknowns_router)
app.include_router(clusters_router)
app.include_router(kyc_router)
app.include_router(liveness_router)
app.include_router(access_router)
app.include_router(audit_router)
app.include_router(compliance_router)
app.include_router(tenants_router)
app.include_router(voice_router)
app.include_router(affect_router)
app.include_router(webhooks_router)
app.include_router(learning_router)
app.include_router(ws_router)

if settings.metrics_enabled:
    from observability.metrics import metrics_text
    @app.get("/metrics", include_in_schema=False)
    async def prometheus_metrics():
        return metrics_text()


# ============================================================
# ENDPOINTS UTILITAIRES
# ============================================================

@app.get("/", tags=["Santé"])
async def root():
    return {
        "service": "Biometric Recognition System",
        "version": "2.0.0",
        "status":  "running",
        "docs":    "/docs",
    }


@app.get("/health", tags=["Santé"])
async def health_check():
    """Vérification santé pour Docker/Kubernetes."""
    checks = {}

    try:
        from database.supabase_client import get_supabase
        get_supabase().table("cameras").select("id").limit(1).execute()
        checks["supabase"] = "ok"
    except Exception as e:
        checks["supabase"] = f"error: {e}"

    try:
        from pipeline import get_pipeline
        get_pipeline()
        checks["ai_pipeline"] = "ok"
    except Exception as e:
        checks["ai_pipeline"] = f"error: {e}"

    checks["redis"] = "ok" if redis_cache.is_enabled() else "disabled"

    idx = faiss_index.get_faiss_index()
    checks["faiss"] = f"ready ({idx.size} vecteurs)" if idx.ready else "not_ready"

    all_ok = all(v.startswith("ok") or v.startswith("ready") or v == "disabled"
                 for v in checks.values())
    return JSONResponse(
        status_code=200 if all_ok else 503,
        content={
            "status":  "healthy" if all_ok else "degraded",
            "checks":  checks,
            "gpu":     settings.gpu_enabled,
            "model":   settings.face_detection_model,
        }
    )


@app.get("/api/v1/stats", tags=["Analytics"])
async def get_stats():
    """Statistiques générales du système."""
    from database.supabase_client import get_supabase
    sb = get_supabase()

    identities  = sb.table("identities").select("id", count="exact").execute()
    embeddings  = sb.table("face_embeddings").select("id", count="exact").execute()
    events      = sb.table("recognition_events").select("id", count="exact").execute()
    unknowns    = sb.table("unknown_faces").select("id", count="exact").eq("resolved", False).execute()

    return {
        "identities":       identities.count or 0,
        "embeddings":       embeddings.count or 0,
        "total_events":     events.count or 0,
        "pending_unknowns": unknowns.count or 0,
        "faiss":            faiss_index.get_faiss_index().stats(),
        "redis_enabled":    redis_cache.is_enabled(),
    }


# ============================================================
# GESTION D'ERREURS GLOBALE
# ============================================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Erreur non gérée: {exc} | {request.url}")
    return JSONResponse(
        status_code=500,
        content={"success": False, "error": "Erreur interne", "detail": str(exc)}
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
        workers=1,
    )
