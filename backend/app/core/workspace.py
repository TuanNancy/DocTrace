"""Workspace selection dependency for workspace-scoped routes.

``X-Workspace-Id`` selects a tenant; it never grants access. Authentication runs
first, then the header is validated and membership is checked against Postgres.
"""
from __future__ import annotations

from fastapi import Depends, Header
from uuid import UUID

from app.core.auth import require_supabase_user
from app.core.errors import api_error
from app.services.workspaces import (
    WorkspaceContext, WorkspaceService, get_workspace_service,
)


async def require_workspace(
    user: dict = Depends(require_supabase_user),
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    service: WorkspaceService = Depends(get_workspace_service),
) -> WorkspaceContext:
    user_id = str(user.get("id") or "")
    if not user_id:
        raise api_error(401, "invalid_session", "Phiên đăng nhập không hợp lệ.")
    workspace_id = (x_workspace_id or "").strip()
    if not workspace_id:
        raise api_error(400, "workspace_required", "Thiếu header X-Workspace-Id.")
    try:
        UUID(workspace_id)
    except ValueError:
        raise api_error(400, "workspace_invalid", "X-Workspace-Id không hợp lệ.") from None
    return await service.resolve(user_id, workspace_id)
