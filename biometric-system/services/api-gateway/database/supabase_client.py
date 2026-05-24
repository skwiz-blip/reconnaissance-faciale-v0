"""
Client Supabase — utilise la service_role key côté backend
pour contourner le RLS et avoir accès complet.
"""
from supabase import create_client, Client
from loguru import logger
import numpy as np
from typing import Optional
from config import get_settings

settings = get_settings()

# Client avec service_role (backend uniquement — jamais exposé au frontend)
_client: Optional[Client] = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        key = settings.supabase_service_key or settings.supabase_anon_key
        _client = create_client(settings.supabase_url, key)
        logger.info(f"Supabase connecté → {settings.supabase_url}")
    return _client


# ============================================================
# IDENTITÉS
# ============================================================

async def get_identity(identity_id: str) -> Optional[dict]:
    sb = get_supabase()
    res = sb.table("identities").select("*").eq("id", identity_id).single().execute()
    return res.data


async def create_identity(data: dict) -> dict:
    sb = get_supabase()
    res = sb.table("identities").insert(data).execute()
    return res.data[0]


async def list_identities(limit: int = 50, offset: int = 0) -> list:
    sb = get_supabase()
    res = (
        sb.table("identities")
        .select("id, full_name, email, role, status, created_at")
        .range(offset, offset + limit - 1)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data


# ============================================================
# EMBEDDINGS
# ============================================================

async def save_embedding(identity_id: str, embedding: np.ndarray,
                          quality: float = 0.9,
                          source: str = "webcam",
                          is_primary: bool = False) -> dict:
    """
    Sauvegarde un embedding. Si EMBEDDING_ENCRYPTION_ENABLED=true,
    chiffre AES-GCM et stocke dans `embedding_encrypted`. Sinon, fallback
    sur la colonne vector classique.
    """
    sb = get_supabase()
    from security import encrypt_embedding, is_encryption_enabled

    payload = {
        "identity_id":    identity_id,
        "quality_score":  quality,
        "capture_source": source,
        "is_primary":     is_primary,
    }
    if is_encryption_enabled():
        payload["embedding_encrypted"] = encrypt_embedding(embedding)
        payload["encryption_version"]  = 1
        # On garde la colonne `embedding` vide pour ne pas dupliquer en clair
        # (la colonne reste nullable côté SQL puisqu'on ne l'utilise plus).
        # Si la colonne est NOT NULL dans ton schéma actuel, stocke un zero-vector:
        payload["embedding"] = np.zeros(512, dtype=np.float32).tolist()
    else:
        payload["embedding"] = embedding.tolist()

    res = sb.table("face_embeddings").insert(payload).execute()
    return res.data[0]


async def get_embeddings_for_identity(identity_id: str) -> list:
    sb = get_supabase()
    res = (
        sb.table("face_embeddings")
        .select("id, embedding, quality_score, is_primary, created_at")
        .eq("identity_id", identity_id)
        .execute()
    )
    return res.data


# ============================================================
# RECHERCHE VECTORIELLE via RPC (pgvector)
# ============================================================

async def search_face_embedding(
    embedding: np.ndarray,
    threshold: float = 0.6,
    limit: int = 5
) -> list:
    """
    Appelle la fonction SQL search_face() définie dans le schema.
    Retourne les identités les plus proches triées par similarité.
    """
    sb = get_supabase()
    res = sb.rpc("search_face", {
        "query_embedding": embedding.tolist(),
        "match_threshold": threshold,
        "match_count": limit,
    }).execute()
    return res.data or []


async def search_unknown_embedding(
    embedding: np.ndarray,
    threshold: float = 0.75
) -> list:
    sb = get_supabase()
    res = sb.rpc("search_unknown_faces", {
        "query_embedding": embedding.tolist(),
        "match_threshold": threshold,
        "match_count": 3,
    }).execute()
    return res.data or []


# ============================================================
# INCONNUS
# ============================================================

async def save_unknown_face(temp_id: str,
                             embedding: np.ndarray,
                             image_url: str = None,
                             location: str = None) -> dict:
    sb = get_supabase()
    res = sb.table("unknown_faces").insert({
        "temp_id":   temp_id,
        "embedding": embedding.tolist(),
        "image_url": image_url,
        "location":  location,
    }).execute()
    return res.data[0]


async def increment_unknown_appearance(unknown_id: str) -> None:
    sb = get_supabase()
    # Increment appearances + update last_seen
    sb.rpc("increment_unknown_appearances", {"unknown_id": unknown_id}).execute()


async def resolve_unknown_face(unknown_id: str, identity_id: str) -> dict:
    sb = get_supabase()
    res = (
        sb.table("unknown_faces")
        .update({"resolved": True, "resolved_as": identity_id})
        .eq("id", unknown_id)
        .execute()
    )
    return res.data[0]


# ============================================================
# ÉVÉNEMENTS DE RECONNAISSANCE
# ============================================================

async def log_recognition_event(data: dict) -> dict:
    sb = get_supabase()
    res = sb.table("recognition_events").insert(data).execute()
    return res.data[0]


async def get_recent_events(limit: int = 20,
                             camera_id: str = None) -> list:
    sb = get_supabase()
    query = (
        sb.table("recognition_events")
        .select("*, identities(full_name, role)")
        .order("created_at", desc=True)
        .limit(limit)
    )
    if camera_id:
        query = query.eq("camera_id", camera_id)
    return query.execute().data


# ============================================================
# ACCÈS
# ============================================================

async def log_access(identity_id: str,
                     event_id: str,
                     access_point: str,
                     decision: str,
                     reason: str = None,
                     zone: str = None) -> dict:
    sb = get_supabase()
    res = sb.table("access_logs").insert({
        "identity_id":  identity_id,
        "event_id":     event_id,
        "access_point": access_point,
        "decision":     decision,
        "reason":       reason,
        "zone":         zone,
    }).execute()
    return res.data[0]


# ============================================================
# STOCKAGE IMAGES (Supabase Storage)
# ============================================================

async def upload_image(bucket: str, path: str,
                        image_bytes: bytes,
                        content_type: str = "image/jpeg") -> str:
    sb = get_supabase()
    sb.storage.from_(bucket).upload(
        path=path,
        file=image_bytes,
        file_options={"content-type": content_type, "upsert": "true"}
    )
    url = sb.storage.from_(bucket).get_public_url(path)
    return url
