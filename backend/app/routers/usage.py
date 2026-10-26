"""GET /api/usage: plan limits, monthly counters and owner-scoped costs.

Postgres owns plan limits, the monthly question counter and cost rows. The
document count comes from the Redis catalog, so the response always matches
what the upload quota enforces. Members only see their own per-user breakdown;
owners see every user in the workspace.
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
    # Documents are workspace-wide, regardless of which member owns them.
    used = await repository.count_workspace(workspace.workspace_id)
    documents = payload["documents"]
    documents["used"] = used
    documents["remaining"] = max(0, documents["limit"] - used)
    return payload
