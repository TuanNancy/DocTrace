"""Uploads retain bytes and enqueue work; extraction belongs to the worker."""
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException

PDF = b"%PDF-1.4\nfixture"
OWNER = "00000000-0000-0000-0000-000000000001"


@pytest.fixture(autouse=True)
def storage():
    with patch("app.routers.upload.is_pdf_storage_configured", return_value=True), \
         patch("app.routers.upload.upload_pdf_to_supabase_storage") as upload, \
         patch("app.routers.upload.delete_pdf"):
        yield upload


@pytest.mark.parametrize("name,content,mime,detail", [
    ("doc.pdf", PDF, "text/plain", "Invalid file type"),
    ("doc.txt", PDF, "application/pdf", "pdf extension"),
    ("doc.pdf", b"", "application/pdf", "Empty file"),
    ("doc.pdf", b"not PDF", "application/pdf", "Invalid PDF header"),
])
def test_upload_validation_never_stores_or_queues(client, repository, storage, name, content, mime, detail):
    response = client.post("/api/upload", files={"file": (name, content, mime)})
    assert response.status_code == 400
    assert detail in response.json()["detail"]
    storage.assert_not_called()
    repository.create.assert_not_awaited()


def test_upload_rejects_file_too_large(client, storage):
    config = MagicMock(upload_max_size_mb=0, upload_allowed_content_types=("application/pdf",))
    with patch("app.routers.upload.get_config", return_value=config):
        response = client.post("/api/upload", files={"file": ("large.pdf", PDF, "application/pdf")})
    assert response.status_code == 413
    storage.assert_not_called()


def test_upload_returns_accepted_only_after_original_is_retained(client, repository, storage):
    response = client.post("/api/upload", files={"file": ("sample.pdf", PDF, "application/pdf")})
    assert response.status_code == 202
    body = response.json()
    UUID(body["doc_id"])
    assert body["status"] == "queued"
    assert body["chunks_count"] == 0
    record = repository.create.call_args.args[0]
    assert record["user_id"] == OWNER
    assert record["size_bytes"] == len(PDF)
    storage.assert_called_once_with(PDF, record["storage_key"])
    repository.check_available.assert_awaited_once()
    assert "storage_key" not in body and "user_id" not in body


def test_storage_failure_never_creates_a_job(client, repository, storage):
    storage.side_effect = RuntimeError("private S3 details")
    response = client.post("/api/upload", files={"file": ("sample.pdf", PDF, "application/pdf")})
    assert response.status_code == 503
    assert "private S3 details" not in response.text
    repository.create.assert_not_awaited()


def test_missing_storage_is_not_reported_as_success(client, repository):
    with patch("app.routers.upload.is_pdf_storage_configured", return_value=False):
        response = client.post("/api/upload", files={"file": ("sample.pdf", PDF, "application/pdf")})
    assert response.status_code == 503
    repository.create.assert_not_awaited()


def test_redis_outage_is_rejected_before_storing_pdf(client, repository, storage):
    repository.check_available.side_effect = HTTPException(503, "Redis unavailable")
    assert client.post("/api/upload", files={"file": ("sample.pdf", PDF, "application/pdf")}).status_code == 503
    storage.assert_not_called()
    repository.create.assert_not_awaited()


def test_lost_enqueue_response_rereads_catalog_without_deleting_pdf(client, repository):
    repository.create.side_effect = HTTPException(503, "Reply lost")
    with patch("app.routers.upload.delete_pdf") as delete:
        response = client.post("/api/upload", files={"file": ("sample.pdf", PDF, "application/pdf")})
    assert response.status_code == 202
    repository.get.assert_awaited_once()
    delete.assert_not_called()


@pytest.mark.parametrize("read_status,deleted", [(404, True), (503, False)])
def test_failed_enqueue_only_removes_pdf_when_noncommit_is_confirmed(client, repository, read_status, deleted):
    repository.create.side_effect = HTTPException(503, "Redis unavailable")
    repository.get.side_effect = HTTPException(read_status, "Cannot read document")
    with patch("app.routers.upload.delete_pdf") as delete:
        response = client.post("/api/upload", files={"file": ("sample.pdf", PDF, "application/pdf")})
    assert response.status_code == 503
    assert delete.called is deleted
