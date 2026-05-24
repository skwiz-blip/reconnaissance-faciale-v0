"""
Router audit logs — consultation (admin uniquement).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from auth.dependencies import require_admin, AuthenticatedUser
from database.supabase_client import get_supabase
from models.schemas_v3 import AuditLogResponse


router = APIRouter(
    prefix="/api/v1/audit",
    tags=["Audit"],
    dependencies=[Depends(require_admin)],
)


@router.get("", response_model=list[AuditLogResponse])
async def list_audit_logs(
    limit:      int = Query(100, ge=1, le=500),
    offset:     int = Query(0, ge=0),
    action:     str | None = Query(None, description="Filtre exact ou préfixe"),
    actor_id:   str | None = None,
    target_type: str | None = None,
):
    sb = get_supabase()
    q = sb.table("audit_logs").select("*").order("created_at", desc=True).range(offset, offset + limit - 1)
    if action:
        if action.endswith("*"):
            q = q.like("action", action[:-1] + "%")
        else:
            q = q.eq("action", action)
    if actor_id:
        q = q.eq("actor_id", actor_id)
    if target_type:
        q = q.eq("target_type", target_type)
    return [AuditLogResponse(**row) for row in q.execute().data or []]
