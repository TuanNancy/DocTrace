"""Authenticated platform administration. Content endpoints stay owner-only."""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core.auth import require_supabase_user
from app.services.admin import AdminService, get_admin_service

router = APIRouter(prefix="/api/admin", tags=["admin"])


class PlanChange(BaseModel):
    plan: Literal["free", "pro"]


class PurgeConfirmation(BaseModel):
    confirm_workspace_id: UUID


@router.get("/access")
async def access(user: dict = Depends(require_supabase_user), service: AdminService = Depends(get_admin_service)):
    await service.assert_admin(str(user["id"]))
    return {"admin": True}


@router.post("/workspaces/{workspace_id}/archive")
async def archive(workspace_id: UUID, user: dict = Depends(require_supabase_user),
                  service: AdminService = Depends(get_admin_service)):
    return await service.archive(str(user["id"]), str(workspace_id))


@router.post("/workspaces/{workspace_id}/restore")
async def restore(workspace_id: UUID, user: dict = Depends(require_supabase_user),
                  service: AdminService = Depends(get_admin_service)):
    return await service.restore(str(user["id"]), str(workspace_id))


@router.get("/overview")
async def overview(days: int = Query(30, ge=1, le=90), user: dict = Depends(require_supabase_user),
                   service: AdminService = Depends(get_admin_service)):
    return await service.overview(str(user["id"]), days)


@router.get("/workspaces")
async def workspaces(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=100000),
                     user: dict = Depends(require_supabase_user), service: AdminService = Depends(get_admin_service)):
    return await service.workspaces(str(user["id"]), limit, offset)


@router.patch("/workspaces/{workspace_id}/plan")
async def change_plan(workspace_id: UUID, payload: PlanChange, user: dict = Depends(require_supabase_user),
                      service: AdminService = Depends(get_admin_service)):
    return await service.change_plan(str(user["id"]), str(workspace_id), payload.plan)


@router.get("/documents")
async def documents(workspace_id: UUID | None = None,
                    status: Literal["queued", "processing", "ready", "error", "deleting", "delete_error"] | None = None,
                    limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=100000),
                    user: dict = Depends(require_supabase_user), service: AdminService = Depends(get_admin_service)):
    return await service.documents(str(user["id"]), str(workspace_id) if workspace_id else None, status, limit, offset)


@router.post("/workspaces/{workspace_id}/purge", status_code=202)
async def purge(workspace_id: UUID, payload: PurgeConfirmation, user: dict = Depends(require_supabase_user),
                service: AdminService = Depends(get_admin_service)):
    from app.core.errors import api_error

    await service.assert_admin(str(user["id"]))
    if payload.confirm_workspace_id != workspace_id:
        raise api_error(400, "purge_confirmation_required", "Nhập đúng ID workspace để xác nhận xóa.")
    return await service.start_purge(str(user["id"]), str(workspace_id))


@router.get("/purges")
async def purges(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=100000),
                 user: dict = Depends(require_supabase_user), service: AdminService = Depends(get_admin_service)):
    return await service.purges(str(user["id"]), limit, offset)


@router.post("/documents/{doc_id}/retry", status_code=202)
async def retry(doc_id: UUID, user: dict = Depends(require_supabase_user),
                service: AdminService = Depends(get_admin_service)):
    return await service.retry(str(user["id"]), str(doc_id))


@router.get("/failures")
async def failures(workspace_id: UUID | None = None, limit: int = Query(50, ge=1, le=100),
                   offset: int = Query(0, ge=0, le=100000), user: dict = Depends(require_supabase_user),
                   service: AdminService = Depends(get_admin_service)):
    return await service.failures(str(user["id"]), str(workspace_id) if workspace_id else None, limit, offset)


@router.get("/audit")
async def audit(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0, le=100000),
                user: dict = Depends(require_supabase_user), service: AdminService = Depends(get_admin_service)):
    return await service.audit(str(user["id"]), limit, offset)


@router.get("/health")
async def health(user: dict = Depends(require_supabase_user), service: AdminService = Depends(get_admin_service)):
    return await service.health(str(user["id"]))
