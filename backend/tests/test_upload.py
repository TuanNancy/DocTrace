"""Uploads retain bytes and enqueue work; extraction belongs to the worker."""
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest

PDF = b"%PDF-1.4\nfixture"
OWNER = "00000000-0000-0000-0000-000000000001"


@pytest.fixture(autouse=True)
def storage():
    with patch("app.routers.upload.is_pdf_storage_configured", return_value=True), \
         patch("app.routers.upload.upload_pdf_to_supabase_storage") as upload:
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
    assert record["status"] == "uploading"
    storage.assert_called_once_with(PDF, record["storage_key"])
    repository.queue.assert_awaited_once_with(OWNER, body["doc_id"], "index")
    assert "storage_key" not in body and "user_id" not in body


def test_storage_failure_is_recorded_without_enqueuing(client, repository, storage):
    storage.side_effect = RuntimeError("private S3 details")
    response = client.post("/api/upload", files={"file": ("sample.pdf", PDF, "application/pdf")})
    assert response.status_code == 503
    assert "private S3 details" not in response.text
    repository.upload_failed.assert_awaited_once()
    repository.queue.assert_not_awaited()


def test_missing_storage_is_not_reported_as_success(client, repository):
    with patch("app.routers.upload.is_pdf_storage_configured", return_value=False):
        response = client.post("/api/upload", files={"file": ("sample.pdf", PDF, "application/pdf")})
    assert response.status_code == 503
    repository.create.assert_not_awaited()
