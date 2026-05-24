"""
Router: Gestion des identités
CRUD identités + enrôlement facial
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../ai-core"))

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from loguru import logger

from models.schemas import (
    IdentityCreate, IdentityUpdate, IdentityResponse,
    EnrollRequest, EnrollResponse,
    ResolveUnknownRequest, SuccessResponse, PaginatedResponse,
    UnknownFaceResponse,
)
from database.supabase_client import (
    create_identity, get_identity, list_identities,
    resolve_unknown_face, get_supabase,
)
from auth.dependencies import require_user, require_admin, AuthenticatedUser
from services.search_service import remove_identity_from_index

router = APIRouter(
    prefix="/api/v1/identities",
    tags=["Identités"],
    dependencies=[Depends(require_user)],
)


# ============================================================
# CRUD IDENTITÉS
# ============================================================

@router.post(
    "",
    response_model=IdentityResponse,
    status_code=201,
    dependencies=[Depends(require_admin)],
)
async def create_new_identity(data: IdentityCreate):
    """Crée une nouvelle identité dans le système (admin uniquement)."""
    try:
        record = await create_identity(data.model_dump(exclude_none=True))
        return IdentityResponse(**record)
    except Exception as e:
        logger.error(f"Create identity: {e}")
        raise HTTPException(400, str(e))


@router.get("", response_model=PaginatedResponse)
async def list_all_identities(
    limit:  int = Query(50, ge=1, le=200),
    offset: int = Query(0,  ge=0),
):
    """Liste toutes les identités avec pagination."""
    items = await list_identities(limit=limit, offset=offset)
    return PaginatedResponse(items=items, total=len(items),
                             limit=limit, offset=offset)


@router.get("/{identity_id}", response_model=IdentityResponse)
async def get_one_identity(identity_id: str):
    """Récupère une identité par ID."""
    record = await get_identity(identity_id)
    if not record:
        raise HTTPException(404, "Identité non trouvée")
    return IdentityResponse(**record)


@router.patch("/{identity_id}", response_model=IdentityResponse)
async def update_identity(identity_id: str, data: IdentityUpdate):
    """Met à jour une identité."""
    sb = get_supabase()
    update_data = data.model_dump(exclude_none=True)
    if not update_data:
        raise HTTPException(400, "Aucune donnée à mettre à jour")
    res = sb.table("identities").update(update_data).eq("id", identity_id).execute()
    if not res.data:
        raise HTTPException(404, "Identité non trouvée")
    return IdentityResponse(**res.data[0])


@router.delete(
    "/{identity_id}",
    response_model=SuccessResponse,
    dependencies=[Depends(require_admin)],
)
async def delete_identity(identity_id: str):
    """Supprime une identité et tous ses embeddings (CASCADE). Évince aussi FAISS + Redis."""
    sb = get_supabase()
    res = sb.table("identities").delete().eq("id", identity_id).execute()
    if not res.data:
        raise HTTPException(404, "Identité non trouvée")
    removed = await remove_identity_from_index(identity_id)
    return SuccessResponse(
        message=f"Identité {identity_id} supprimée ({removed} vecteurs évincés de FAISS)"
    )


# ============================================================
# ENRÔLEMENT FACIAL
# ============================================================

@router.post("/{identity_id}/enroll", response_model=EnrollResponse)
async def enroll_face_base64(identity_id: str, req: EnrollRequest):
    """
    Enrôle un visage pour une identité existante (image base64).
    Peut être appelé plusieurs fois pour enrichir le profil biométrique.
    """
    identity = await get_identity(identity_id)
    if not identity:
        raise HTTPException(404, "Identité non trouvée")

    from pipeline import get_pipeline
    import base64

    pipeline = get_pipeline()

    b64 = req.image_base64
    if "," in b64:
        b64 = b64.split(",")[1]
    image_bytes = base64.b64decode(b64)

    result = await pipeline.enroll_face(image_bytes, identity_id)
    return EnrollResponse(**result)


@router.post("/{identity_id}/enroll/upload", response_model=EnrollResponse)
async def enroll_face_upload(
    identity_id: str,
    file: UploadFile = File(...),
):
    """Enrôle un visage via upload fichier."""
    identity = await get_identity(identity_id)
    if not identity:
        raise HTTPException(404, "Identité non trouvée")

    image_bytes = await file.read()

    from pipeline import get_pipeline
    pipeline = get_pipeline()

    result = await pipeline.enroll_face(image_bytes, identity_id)
    return EnrollResponse(**result)


@router.get("/{identity_id}/embeddings")
async def list_embeddings(identity_id: str):
    """Liste les embeddings d'une identité."""
    from database.supabase_client import get_embeddings_for_identity
    embeddings = await get_embeddings_for_identity(identity_id)
    # Ne pas retourner les vecteurs bruts (512 floats) dans la liste
    return [{
        "id":           e["id"],
        "quality_score": e["quality_score"],
        "is_primary":   e["is_primary"],
        "created_at":   e["created_at"],
    } for e in embeddings]


# ============================================================
# INCONNUS
# ============================================================

unknowns_router = APIRouter(
    prefix="/api/v1/unknowns",
    tags=["Inconnus"],
    dependencies=[Depends(require_user)],
)


@unknowns_router.get("")
async def list_unknown_faces(
    limit:  int = Query(50, ge=1, le=200),
    offset: int = Query(0,  ge=0),
):
    """Liste les visages inconnus non résolus."""
    sb = get_supabase()
    res = (
        sb.table("unknown_faces")
        .select("id, temp_id, appearances, first_seen_at, last_seen_at, location, cluster_id, image_url")
        .eq("resolved", False)
        .order("last_seen_at", desc=True)
        .range(offset, offset + limit - 1)
        .execute()
    )
    return res.data


@unknowns_router.post(
    "/{unknown_id}/resolve",
    response_model=SuccessResponse,
    dependencies=[Depends(require_admin)],
)
async def resolve_unknown(unknown_id: str, req: ResolveUnknownRequest):
    """
    Résout un visage inconnu :
    - En l'associant à une identité existante
    - Ou en créant une nouvelle identité
    """
    identity_id = req.identity_id

    if not identity_id and req.new_identity:
        # Créer une nouvelle identité
        record = await create_identity(req.new_identity.model_dump(exclude_none=True))
        identity_id = record["id"]

    if not identity_id:
        raise HTTPException(400, "identity_id ou new_identity requis")

    await resolve_unknown_face(unknown_id, identity_id)

    # Transférer l'embedding vers face_embeddings + index FAISS
    sb = get_supabase()
    unknown = sb.table("unknown_faces").select("embedding").eq("id", unknown_id).single().execute()
    if unknown.data:
        import numpy as np
        from database.supabase_client import save_embedding
        from services.search_service import add_embedding_to_index
        emb = np.array(unknown.data["embedding"], dtype=np.float32)
        saved = await save_embedding(
            identity_id, emb, quality=0.7, source="unknown_resolved"
        )
        await add_embedding_to_index(saved["id"], identity_id, emb)

    return SuccessResponse(
        message=f"Inconnu {unknown_id} associé à l'identité {identity_id}"
    )
