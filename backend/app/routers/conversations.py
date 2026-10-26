"""Owner-scoped transcript reads and deletion.

Conversations are always filtered by workspace and the authenticated user.
Workspace owners only see aggregate usage, never a member's messages. A
conversation from a deleted document is hidden immediately and only becomes
visible again through the retention purge boundary, not through these routes.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core.errors import api_error
from app.core.workspace import require_workspace
from app.services.document_repository import DocumentRepository, get_document_repository
from app.services.transcripts import (
    TranscriptService, get_transcript_service, stale_sources,
)
from app.services.workspaces import WorkspaceContext

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("")
async def list_conversations(
    doc_id: UUID | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    workspace: WorkspaceContext = Depends(require_workspace),
    transcripts: TranscriptService = Depends(get_transcript_service),
):
    """Latest active conversations for the current user; optional document filter."""
    return await transcripts.list(
        workspace.workspace_id, workspace.user_id,
        str(doc_id) if doc_id else None, limit,
    )


@router.get("/{conversation_id}")
async def get_conversation(
    conversation_id: UUID,
    workspace: WorkspaceContext = Depends(require_workspace),
    transcripts: TranscriptService = Depends(get_transcript_service),
    repository: DocumentRepository = Depends(get_document_repository),
):
    conversation = await transcripts.get(
        workspace.workspace_id, workspace.user_id, str(conversation_id),
    )
    if not conversation:
        raise api_error(404, "conversation_not_found", "Không tìm thấy hội thoại.")

    # The citation snapshot keeps the Milvus generation it was produced from.
    # A missing, non-ready or re-indexed document makes every source stale;
    # the client must not fetch an old chunk id from the new generation.
    active_index_id: str | None = None
    try:
        document = await repository.get(
            workspace.workspace_id, workspace.user_id, conversation["doc_id"],
        )
        if document["status"] == "ready":
            active_index_id = document.get("active_index_id")
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
    return stale_sources(conversation, active_index_id)


@router.delete("/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID,
    workspace: WorkspaceContext = Depends(require_workspace),
    transcripts: TranscriptService = Depends(get_transcript_service),
):
    """Delete the current user's conversation and messages immediately.

    The demo has no conversation history UI, so "new chat" removes the old
    transcript rather than leaving an inaccessible archive behind. Document
    deletion uses the separate retention path in the document router.
    """
    deleted = await transcripts.delete(
        workspace.workspace_id, workspace.user_id, str(conversation_id),
    )
    if not deleted:
        raise api_error(404, "conversation_not_found", "Không tìm thấy hội thoại.")
    return Response(status_code=204)
