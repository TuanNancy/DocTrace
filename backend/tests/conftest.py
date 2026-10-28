"""
Pytest fixtures: FastAPI TestClient and app.
"""
import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

# Ensure backend app is on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import config as config_module

# Prevent app construction and tests from loading developers' .env files.
config_module._config = config_module.AppConfig(
    model="test-model", embedding_model="test-embedding", openrouter_api_key="test-key",
)

from app.core.auth import require_supabase_user
from app.core.workspace import require_workspace
from app.main import app
from app.services.document_repository import DocumentRepository, get_document_repository
from app.services.quotas import QuotaService, get_quota_service
from app.services.rate_limiter import RateLimiter, get_rate_limiter
from app.services.transcripts import TranscriptService, get_transcript_service
from app.services.workspaces import WorkspaceContext, WorkspaceService, get_workspace_service

CHAT_REQUEST_ID = "00000000-0000-0000-0000-0000000000c1"


async def _fake_supabase_user():
    return {"id": "00000000-0000-0000-0000-000000000001", "email": "test@example.com"}


async def _fake_workspace():
    return WorkspaceContext(
        workspace_id="00000000-0000-0000-0000-0000000000ab",
        user_id="00000000-0000-0000-0000-000000000001",
        role="owner", plan="free", kind="personal", name="Cá nhân",
    )


@pytest.fixture
def repository():
    """Only the Redis library boundary is mocked; no developer cloud calls."""
    fake = AsyncMock(spec=DocumentRepository)
    fake.get.side_effect = lambda workspace_id, uid, doc_id: {
        "doc_id": doc_id, "workspace_id": workspace_id, "owner_user_id": uid, "user_id": uid,
        "name": "sample.pdf", "status": "ready",
        "active_index_id": doc_id, "storage_key": f"{uid}/{doc_id}/sample.pdf",
    }
    fake.get_sync.side_effect = fake.get.side_effect
    fake.transcript_documents.side_effect = lambda workspace_id, uid, doc_ids: {
        doc_id: fake.get_sync(workspace_id, uid, doc_id) for doc_id in doc_ids
    }
    fake.create.side_effect = lambda document, *, limit: {
        **document, "status": "queued", "chunks_count": 0, "warnings": [], "error": None,
    }
    fake.queue.side_effect = lambda workspace_id, uid, doc_id, kind: {
        "doc_id": doc_id, "name": "sample.pdf", "status": "queued" if kind == "index" else "deleting",
        "chunks_count": 0, "size_bytes": 100, "warnings": [], "user_id": uid,
        "workspace_id": workspace_id, "owner_user_id": uid,
    }
    fake.list.return_value = {"items": [], "has_more": False}
    fake.count_workspace.return_value = 0
    return fake


@pytest.fixture
def workspace_service(repository):
    fake = AsyncMock(spec=WorkspaceService)

    async def create(document, repo, *, limit):
        return await repo.create(document, limit=limit)

    fake.create_document.side_effect = create
    return fake


@pytest.fixture
def quotas():
    """No Postgres in unit tests; quota SQL is covered by the Docker-gated suite."""
    fake = AsyncMock(spec=QuotaService)
    fake.existing_chat.return_value = None
    fake.admit_chat.return_value = {
        "chat_request_id": CHAT_REQUEST_ID,
        "request_id": "00000000-0000-0000-0000-0000000000c2",
        "conversation_id": "00000000-0000-0000-0000-0000000000c3",
        "assistant_message_id": "00000000-0000-0000-0000-0000000000c4",
        "used": 1,
        "limit": 10,
        "reset_at": "2026-11-01T00:00:00Z",
    }
    fake.document_limit.return_value = 5
    fake.mark_chat_status.return_value = True
    fake.usage.return_value = {
        "workspace_id": "00000000-0000-0000-0000-0000000000ab",
        "scope": "workspace",
        "plan": "free",
        "period_start": "2026-10-01",
        "reset_at": "2026-11-01T00:00:00Z",
        "chat": {"used": 1, "limit": 10, "remaining": 9, "metric": "chat_questions_month"},
        "documents": {"used": 0, "limit": 5, "remaining": 5, "metric": "documents"},
        "by_user": [],
        "costs": {"known_micros": 0, "unknown_calls": 0},
    }
    return fake


@pytest.fixture
def rate_limiter():
    return AsyncMock(spec=RateLimiter)


@pytest.fixture
def transcripts():
    fake = AsyncMock(spec=TranscriptService)
    fake.list.return_value = {"items": []}
    fake.get.return_value = None
    fake.delete.return_value = False
    fake.mark_streaming.return_value = True
    fake.finalize_message.return_value = True
    fake.hide_for_document.return_value = 0

    async def queue_deletion(workspace_id, user_id, doc_id, repository):
        return await repository.queue(workspace_id, user_id, doc_id, "delete")

    fake.queue_document_deletion.side_effect = queue_deletion
    return fake


@pytest.fixture
def client(repository, quotas, rate_limiter, transcripts, workspace_service) -> TestClient:
    """FastAPI TestClient for router tests."""
    app.dependency_overrides[require_supabase_user] = _fake_supabase_user
    app.dependency_overrides[require_workspace] = _fake_workspace
    app.dependency_overrides[get_document_repository] = lambda: repository
    app.dependency_overrides[get_rate_limiter] = lambda: rate_limiter
    app.dependency_overrides[get_quota_service] = lambda: quotas
    app.dependency_overrides[get_transcript_service] = lambda: transcripts
    app.dependency_overrides[get_workspace_service] = lambda: workspace_service
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(require_supabase_user, None)
        app.dependency_overrides.pop(require_workspace, None)
        app.dependency_overrides.pop(get_document_repository, None)
        app.dependency_overrides.pop(get_rate_limiter, None)
        app.dependency_overrides.pop(get_quota_service, None)
        app.dependency_overrides.pop(get_transcript_service, None)
        app.dependency_overrides.pop(get_workspace_service, None)
