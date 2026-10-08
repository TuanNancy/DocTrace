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
from app.main import app
from app.services.document_repository import DocumentRepository, get_document_repository
from app.services.rate_limiter import RateLimiter, get_rate_limiter


async def _fake_supabase_user():
    return {"id": "00000000-0000-0000-0000-000000000001", "email": "test@example.com"}


@pytest.fixture
def repository():
    """Only the Redis library boundary is mocked; no developer cloud calls."""
    fake = AsyncMock(spec=DocumentRepository)
    fake.get.side_effect = lambda uid, doc_id: {
        "doc_id": doc_id, "user_id": uid, "name": "sample.pdf", "status": "ready",
        "active_index_id": doc_id, "storage_key": f"{uid}/{doc_id}/sample.pdf",
    }
    fake.create.side_effect = lambda document: {
        **document, "status": "queued", "chunks_count": 0, "warnings": [], "error": None,
    }
    fake.queue.side_effect = lambda uid, doc_id, kind: {
        "doc_id": doc_id, "name": "sample.pdf", "status": "queued" if kind == "index" else "deleting",
        "chunks_count": 0, "size_bytes": 100, "warnings": [], "user_id": uid,
    }
    fake.list.return_value = {"items": [], "has_more": False}
    return fake


@pytest.fixture
def client(repository) -> TestClient:
    """FastAPI TestClient for router tests."""
    app.dependency_overrides[require_supabase_user] = _fake_supabase_user
    app.dependency_overrides[get_document_repository] = lambda: repository
    app.dependency_overrides[get_rate_limiter] = lambda: AsyncMock(spec=RateLimiter)
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(require_supabase_user, None)
        app.dependency_overrides.pop(get_document_repository, None)
        app.dependency_overrides.pop(get_rate_limiter, None)
