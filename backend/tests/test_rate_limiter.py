"""Admission failures must precede Storage, enqueue and SSE/provider work."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from redis.exceptions import ConnectionError

from app.core.config import AppConfig
from app.main import app
from app.services.rate_limiter import RateLimiter, get_rate_limiter

OWNER = "00000000-0000-0000-0000-000000000001"
DOC = str(uuid4())


@pytest.fixture
def limiter(client):
    fake = AsyncMock(spec=RateLimiter)
    app.dependency_overrides[get_rate_limiter] = lambda: fake
    try:
        yield fake
    finally:
        app.dependency_overrides.pop(get_rate_limiter, None)


@pytest.mark.parametrize("status", [429, 503])
def test_denied_upload_does_not_store_or_enqueue(client, repository, limiter, status):
    limiter.check.side_effect = HTTPException(status, "Try later", headers={"Retry-After": "12"})
    with patch("app.routers.upload.is_pdf_storage_configured", return_value=True), \
         patch("app.routers.upload.upload_pdf_to_supabase_storage") as store:
        response = client.post("/api/upload", files={"file": ("a.pdf", b"%PDF-1.4", "application/pdf")})
    assert response.status_code == status
    limiter.check.assert_awaited_once_with(OWNER, action="upload")
    store.assert_not_called()
    repository.create.assert_not_awaited()


def test_invalid_upload_does_not_consume_quota(client, limiter):
    response = client.post("/api/upload", files={"file": ("a.pdf", b"invalid", "application/pdf")})
    assert response.status_code == 400
    limiter.check.assert_not_awaited()


@pytest.mark.parametrize("status", [429, 503])
def test_denied_chat_is_json_before_sse_and_exposes_retry_header(client, repository, limiter, status):
    limiter.check.side_effect = HTTPException(status, "Try later", headers={"Retry-After": "12"})
    with patch("app.routers.chat.create_initialized_rag_pipeline", new_callable=AsyncMock) as create:
        response = client.post("/api/chat", json={"query": "hello", "doc_id": DOC},
                               headers={"Origin": "http://localhost:3000"})
    assert response.status_code == status
    assert response.headers["content-type"] == "application/json"
    assert response.headers["retry-after"] == "12"
    assert "retry-after" in response.headers["access-control-expose-headers"].lower()
    assert response.json() == {"detail": "Try later"}
    repository.get.assert_awaited_once_with(OWNER, DOC)
    limiter.check.assert_awaited_once_with(OWNER, action="chat")
    create.assert_not_awaited()


@pytest.mark.parametrize("action", ["chat", "retry"])
@pytest.mark.parametrize("status", [404, 409])
def test_ownership_and_state_checks_precede_quota(client, repository, limiter, action, status):
    repository.get.side_effect = HTTPException(status, "Unavailable")
    response = (client.post("/api/chat", json={"query": "q", "doc_id": DOC}) if action == "chat"
                else client.post(f"/api/documents/{DOC}/retry"))
    assert response.status_code == status
    limiter.check.assert_not_awaited()


def test_unready_document_does_not_consume_chat_quota(client, repository, limiter):
    repository.get.side_effect = None
    repository.get.return_value = {"status": "processing", "active_index_id": None}
    assert client.post("/api/chat", json={"query": "q", "doc_id": DOC}).status_code == 409
    limiter.check.assert_not_awaited()


def test_denied_index_retry_does_not_enqueue(client, repository, limiter):
    repository.get.side_effect = None
    repository.get.return_value = {"status": "error"}
    limiter.check.side_effect = HTTPException(429, "Try later", headers={"Retry-After": "200"})
    assert client.post(f"/api/documents/{DOC}/retry").status_code == 429
    limiter.check.assert_awaited_once_with(OWNER, action="index-retry")
    repository.queue.assert_not_awaited()


def test_allowed_index_retry_checks_verified_user(client, repository, limiter):
    repository.get.side_effect = None
    repository.get.return_value = {"status": "error"}
    assert client.post(f"/api/documents/{DOC}/retry").status_code == 202
    limiter.check.assert_awaited_once_with(OWNER, action="index-retry")
    repository.queue.assert_awaited_once_with(OWNER, DOC, "index")


def test_cleanup_retry_and_reads_are_not_limited(client, repository, limiter):
    repository.get.side_effect = None
    repository.get.return_value = {"status": "delete_error"}
    assert client.post(f"/api/documents/{DOC}/retry").status_code == 202
    assert client.get("/api/documents").status_code == 200
    assert client.get("/health").status_code == 200
    limiter.check.assert_not_awaited()


def test_no_auth_does_not_consume_quota(client, limiter):
    from app.core.auth import require_supabase_user
    override = app.dependency_overrides.pop(require_supabase_user)
    try:
        assert client.post("/api/chat", json={"query": "q", "doc_id": DOC}).status_code == 401
        assert client.post(f"/api/documents/{DOC}/retry").status_code == 401
        assert client.post("/api/upload", files={"file": ("a.pdf", b"%PDF", "application/pdf")}).status_code == 401
    finally:
        app.dependency_overrides[require_supabase_user] = override
    limiter.check.assert_not_awaited()


async def test_disabled_limiter_does_not_connect():
    with patch("app.services.rate_limiter.Redis.from_url") as connect:
        await RateLimiter(AppConfig(rate_limit_enabled=False)).check(OWNER, action="chat")
    connect.assert_not_called()


async def test_redis_failure_is_503_not_quota_exhaustion_and_is_not_retried():
    connection = MagicMock()
    connection.eval.side_effect = ConnectionError("private connection details")
    with patch("app.services.rate_limiter.Redis.from_url") as connect:
        connect.return_value.__enter__.return_value = connection
        with pytest.raises(HTTPException) as caught:
            await RateLimiter(AppConfig()).check(OWNER, action="chat")
    assert caught.value.status_code == 503
    assert "private" not in caught.value.detail
    connection.eval.assert_called_once()
    assert connect.call_args.kwargs["retry"].get_retries() == 0


async def test_quota_error_contains_wait_seconds():
    with patch("app.services.rate_limiter.Redis.from_url") as connect:
        connect.return_value.__enter__.return_value.eval.return_value = 12
        with pytest.raises(HTTPException) as caught:
            await RateLimiter(AppConfig()).check(OWNER, action="chat")
    assert caught.value.status_code == 429
    assert caught.value.headers == {"Retry-After": "12"}
    assert "12 giây" in caught.value.detail
