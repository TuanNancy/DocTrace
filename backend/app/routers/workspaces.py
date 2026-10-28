"""Workspace membership and lifecycle APIs.

Management endpoints select the workspace from the path, not from
``X-Workspace-Id``. Every mutating call re-checks the caller's role in
Postgres; document counts come from the Redis catalog (metadata only).
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends

from app.core.auth import require_supabase_user
from app.schemas import WorkspaceCreate, WorkspaceMemberAdd
from app.services.document_repository import DocumentRepository, get_document_repository
from app.services.workspaces import WorkspaceService, get_workspace_service

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


def _user_id(user: dict) -> str:
    return str(user["id"])


@router.get("")
async def list_workspaces(
    user: dict = Depends(require_supabase_user),
    service: WorkspaceService = Depends(get_workspace_service),
):
    return {"items": await service.list_for_user(_user_id(user))}


@router.post("", status_code=201)
async def create_workspace(
    payload: WorkspaceCreate,
    user: dict = Depends(require_supabase_user),
    service: WorkspaceService = Depends(get_workspace_service),
):
    return await service.create(_user_id(user), payload.name)


@router.get("/{workspace_id}/members")
async def list_members(
    workspace_id: UUID,
    user: dict = Depends(require_supabase_user),
    service: WorkspaceService = Depends(get_workspace_service),
):
    return {"items": await service.members(_user_id(user), str(workspace_id))}


@router.post("/{workspace_id}/members", status_code=201)
async def add_member(
    workspace_id: UUID,
    payload: WorkspaceMemberAdd,
    user: dict = Depends(require_supabase_user),
    service: WorkspaceService = Depends(get_workspace_service),
):
    return await service.add_member(_user_id(user), str(workspace_id), str(payload.user_id))


@router.delete("/{workspace_id}/members/{member_id}")
async def remove_member(
    workspace_id: UUID,
    member_id: UUID,
    user: dict = Depends(require_supabase_user),
    service: WorkspaceService = Depends(get_workspace_service),
    repository: DocumentRepository = Depends(get_document_repository),
):
    # Service authorizes, locks membership, then counts under the upload fence.
    return await service.remove_member(
        _user_id(user), str(workspace_id), str(member_id), repository,
    )


@router.post("/{workspace_id}/archive")
async def archive_workspace(
    workspace_id: UUID,
    user: dict = Depends(require_supabase_user),
    service: WorkspaceService = Depends(get_workspace_service),
):
    return await service.archive(_user_id(user), str(workspace_id))


@router.post("/{workspace_id}/restore")
async def restore_workspace(
    workspace_id: UUID,
    user: dict = Depends(require_supabase_user),
    service: WorkspaceService = Depends(get_workspace_service),
):
    return await service.restore(_user_id(user), str(workspace_id))
