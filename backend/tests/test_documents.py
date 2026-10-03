from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.routers import documents
from app.storage.base import RetrievedChunk

DOC = str(uuid4())
CHUNK = str(uuid4())
OWNER = "00000000-0000-0000-0000-000000000001"


@pytest.mark.parametrize("path", [f"/{DOC}", f"/{DOC}/file", f"/{DOC}/chunks/{CHUNK}"])
def test_unknown_or_foreign_document_never_opens_storage(client, repository, monkeypatch, path):
    repository.get.side_effect = HTTPException(404, "Not found")
    signer = MagicMock()
    connect = AsyncMock()
    monkeypatch.setattr(documents, "signed_pdf_url", signer)
    monkeypatch.setattr(documents, "create_connected_vector_store", connect)
    assert client.get(f"/api/documents{path}").status_code == 404
    repository.get.assert_awaited_once_with(OWNER, DOC)
    signer.assert_not_called()
    connect.assert_not_awaited()


def test_sources_are_scoped_to_owner_and_published_generation(client, repository, monkeypatch):
    repository.get.side_effect = None
    repository.get.return_value = {"status": "ready", "active_index_id": "published-generation", "name": "Original.pdf"}
    store = AsyncMock()
    store.get_chunk.return_value = RetrievedChunk(CHUNK, "published-generation", "Original passage", 3, "Original.pdf", None)
    monkeypatch.setattr(documents, "create_connected_vector_store", AsyncMock(return_value=store))
    response = client.get(f"/api/documents/{DOC}/chunks/{CHUNK}")
    assert response.status_code == 200
    assert response.json()["text"] == "Original passage"
    assert response.json()["doc_id"] == DOC
    store.get_chunk.assert_awaited_once_with("published-generation", CHUNK, user_id=OWNER)
    store.disconnect.assert_awaited_once()


def test_pdf_link_is_short_lived_and_uses_server_owned_key(client, repository, monkeypatch):
    signer = MagicMock(return_value="https://storage.example.test/signed")
    monkeypatch.setattr(documents, "signed_pdf_url", signer)
    response = client.get(f"/api/documents/{DOC}/file")
    assert response.json() == {"url": "https://storage.example.test/signed", "expires_in": 300}
    signer.assert_called_once_with(f"{OWNER}/{DOC}/sample.pdf")


def test_delete_queues_cleanup_under_verified_owner(client, repository):
    response = client.delete(f"/api/documents/{DOC}")
    assert response.status_code == 202
    assert response.json()["status"] == "deleting"
    repository.queue.assert_awaited_once_with(OWNER, DOC, "delete")


def test_retry_delete_failure_keeps_deletion_intent(client, repository):
    repository.get.side_effect = None
    repository.get.return_value = {"status": "delete_error"}
    assert client.post(f"/api/documents/{DOC}/retry").status_code == 202
    repository.queue.assert_awaited_once_with(OWNER, DOC, "delete")


def test_ready_document_cannot_be_reindexed_by_retry(client, repository):
    assert client.post(f"/api/documents/{DOC}/retry").status_code == 409
    repository.queue.assert_not_awaited()


def test_chat_rejects_unready_documents_before_rag(client, repository):
    repository.get.side_effect = None
    repository.get.return_value = {"status": "processing", "active_index_id": None}
    assert client.post("/api/chat", json={"query": "hello", "doc_id": DOC}).status_code == 409


def test_delete_conflict_is_returned_to_client(client, repository):
    repository.queue.side_effect = HTTPException(409, "Wait for current job")
    assert client.delete(f"/api/documents/{DOC}").status_code == 409
