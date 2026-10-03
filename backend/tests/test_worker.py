from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import AppConfig
from app.jobs import documents as tasks
from app.services.pdf_indexing import InvalidPDFError


@pytest.fixture
def attempt():
    return {"operation_id": "operation", "attempt_id": "generation", "kind": "index", "document": {
        "doc_id": "doc", "user_id": "owner", "name": "original.pdf", "storage_key": "owner/doc/original.pdf",
    }}


@pytest.fixture
def dependencies(monkeypatch, attempt):
    repository = AsyncMock(config=AppConfig())
    repository.begin.return_value = attempt
    repository.finish.return_value = True
    repository.internal_document.return_value = {"active_index_id": None, "status": "processing"}
    repository.generations.return_value = ["old", "generation"]
    index = AsyncMock(return_value=SimpleNamespace(chunks_count=3, warnings=[]))
    remove = AsyncMock()
    delete = MagicMock()
    monkeypatch.setattr(tasks, "index_pdf_bytes", index)
    monkeypatch.setattr(tasks, "download_pdf", MagicMock(return_value=b"%PDF-fixture"))
    monkeypatch.setattr(tasks, "remove_generations", remove)
    monkeypatch.setattr(tasks, "delete_pdf", delete)
    return repository, index, remove, delete


async def test_index_uses_attempt_generation_and_publishes(attempt, dependencies):
    repository, index, remove, _ = dependencies
    await tasks.process_document(repository, "operation", 0, "index")
    repository.begin.assert_awaited_once_with("operation", 0, 900)
    index.assert_awaited_once_with(b"%PDF-fixture", "original.pdf", "generation", user_id="owner")
    repository.finish.assert_awaited_once_with(attempt, chunks_count=3, warnings=[])
    remove.assert_not_awaited()  # Cleanup runs independently of publication.


async def test_superseded_delivery_does_no_work(dependencies):
    repository, index, remove, delete = dependencies
    repository.begin.return_value = None
    await tasks.process_document(repository, "operation", 0, "index")
    index.assert_not_awaited()
    delete.assert_not_called()
    repository.finish.assert_not_awaited()


async def test_transient_failure_is_recorded_and_raised_for_rq(attempt, dependencies):
    repository, index, remove, _ = dependencies
    index.side_effect = ConnectionError("private upstream error")
    with pytest.raises(ConnectionError):
        await tasks.process_document(repository, "operation", 0, "index")
    assert repository.finish.call_args.kwargs["retryable"] is True
    assert "private" not in repository.finish.call_args.kwargs["error"]
    remove.assert_not_awaited()


async def test_invalid_pdf_is_terminal_business_failure(dependencies):
    repository, index, _, _ = dependencies
    index.side_effect = InvalidPDFError("No text")
    await tasks.process_document(repository, "operation", 0, "index")
    assert repository.finish.call_args.kwargs["retryable"] is False


async def test_lost_publish_response_does_not_delete_or_mark_ready_document_failed(dependencies):
    repository, _, remove, _ = dependencies
    repository.finish.side_effect = ConnectionError("response lost after commit")
    repository.internal_document.return_value = {"active_index_id": "generation", "status": "ready"}
    await tasks.process_document(repository, "operation", 0, "index")
    assert repository.finish.await_count == 1
    remove.assert_not_awaited()


async def test_unavailable_database_never_guesses_publication_failed(dependencies):
    repository, _, remove, _ = dependencies
    repository.finish.side_effect = ConnectionError()
    repository.internal_document.side_effect = ConnectionError()
    with pytest.raises(ConnectionError):
        await tasks.process_document(repository, "operation", 0, "index")
    assert repository.finish.await_count == 1
    remove.assert_not_awaited()


async def test_delete_retries_both_external_deletions(attempt, dependencies):
    repository, index, remove, delete = dependencies
    attempt["kind"] = "delete"
    delete.side_effect = [ConnectionError(), None]
    with pytest.raises(ConnectionError):
        await tasks.process_document(repository, "operation", 0, "delete")
    await tasks.process_document(repository, "operation", 0, "delete")
    assert remove.await_count == 2
    repository.finish.assert_awaited_with(attempt)
    index.assert_not_awaited()


async def test_cleanup_uses_database_filtered_generations_and_owner(dependencies):
    repository, _, remove, delete = dependencies
    repository.internal_document.return_value = {"user_id": "owner", "status": "ready", "storage_key": "key"}
    repository.cleanup_candidates.return_value = ["retired"]
    await tasks.cleanup(repository, "doc", "timestamp")
    remove.assert_awaited_once_with("owner", ["retired"])
    delete.assert_not_called()
    repository.cleanup_finished.assert_awaited_once_with("doc", "timestamp")


async def test_tombstone_sweep_repeats_physical_deletion(dependencies):
    repository, _, remove, delete = dependencies
    repository.internal_document.return_value = {"user_id": "owner", "status": "deleted", "storage_key": "key"}
    repository.cleanup_candidates.return_value = ["late-write"]
    await tasks.cleanup(repository, "doc", "timestamp")
    remove.assert_awaited_once_with("owner", ["late-write"])
    delete.assert_called_once_with("key")
