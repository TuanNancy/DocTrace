"""GET /api/usage: plan limits, monthly counters and owner-scoped costs.

Postgres owns plan limits, the monthly question counter and cost rows. The
document count comes from the Redis catalog. Owners see workspace aggregates;
members see only self counts/costs and shared plan limits, never shared remaining
quota (which would reveal the workspace total).
"""
from fastapi import APIRouter, Depends

from app.core.workspace import require_workspace
from app.services.document_repository import DocumentRepository, get_document_repository
from app.services.quotas import QuotaService, get_quota_service
from app.services.workspaces import WorkspaceContext

router = APIRouter(prefix="/api", tags=["usage"])


@router.get("/usage")
async def get_usage(
    workspace: WorkspaceContext = Depends(require_workspace),
    repository: DocumentRepository = Depends(get_document_repository),
    quotas: QuotaService = Depends(get_quota_service),
):
    payload = await quotas.usage(
        workspace.workspace_id, workspace.plan, workspace.user_id, workspace.role,
    )
    owner = workspace.role == "owner"
    used = await repository.count_workspace(workspace.workspace_id) if owner else (
        await repository.count_workspace(workspace.workspace_id, workspace.user_id)
    )
    documents = payload["documents"]
    documents["used"] = used
    documents["remaining"] = max(0, documents["limit"] - used) if owner else None
    return payload
