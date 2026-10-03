from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.jobs import documents as tasks
from app.services.pdf_indexing import InvalidPDFError


@pytest.fixture
def attempt():
    return {"job_id": "job", "attempt_id": "generation", "kind": "index", "document": {
        "doc_id": "doc", "user_id": "owner", "name": "original.pdf", "storage_key": "owner/doc/original.pdf",
        "generations": ["old", "generation"],
    }}


@pytest.fixture
def dependencies(monkeypatch, attempt):
    repository = AsyncMock()
    repository.begin.return_value = attempt
    repository.finish.return_value = True
    repository.internal_document.return_value = {"active_index_id": None, "status": "processing"}
    index = AsyncMock(return_value=SimpleNamespace(chunks_count=3, warnings=[]))
    remove = AsyncMock()
    delete = MagicMock()
    monkeypatch.setattr(tasks, "index_pdf_bytes", index)
    monkeypatch.setattr(tasks, "download_pdf", MagicMock(return_value=b"%PDF-fixture"))
    monkeypatch.setattr(tasks, "remove_generations", remove)
    monkeypatch.setattr(tasks, "delete_pdf", delete)
    return repository, index, remove, delete


async def test_retry_cleans_partial_indexes_and_publishes_fresh_generation(attempt, dependencies):
    repository, index, remove, _ = dependencies
    await tasks.process_document(repository, "doc", "job", 2, 1)
    repository.begin.assert_awaited_once_with("doc", "job", 2)
    remove.assert_awaited_once_with("owner", ["old"])
    index.assert_awaited_once_with(b"%PDF-fixture", "original.pdf", "generation", user_id="owner")
    repository.finish.assert_awaited_once_with(attempt, chunks_count=3, warnings=[])


async def test_superseded_job_does_no_work(dependencies):
    repository, index, remove, delete = dependencies
    repository.begin.return_value = None
    await tasks.process_document(repository, "doc", "job", 1, 2)
    index.assert_not_awaited()
    remove.assert_not_awaited()
    delete.assert_not_called()


@pytest.mark.parametrize("remaining,retryable", [(2, True), (0, False)])
async def test_transient_failure_is_raised_for_rq_and_final_failure_is_persisted(dependencies, remaining, retryable):
    repository, index, _, _ = dependencies
    index.side_effect = ConnectionError("private upstream error")
    with pytest.raises(ConnectionError):
        await tasks.process_document(repository, "doc", "job", 3 - remaining, remaining)
    assert repository.finish.call_args.kwargs["retryable"] is retryable
    assert "private" not in repository.finish.call_args.kwargs["error"]


async def test_invalid_pdf_is_terminal_business_failure(dependencies):
    repository, index, _, _ = dependencies
    index.side_effect = InvalidPDFError("No text")
    await tasks.process_document(repository, "doc", "job", 1, 2)
    assert repository.finish.call_args.kwargs["retryable"] is False


async def test_lost_publish_response_does_not_mark_ready_document_failed(dependencies):
    repository, _, remove, _ = dependencies
    repository.finish.side_effect = ConnectionError("response lost after commit")
    repository.internal_document.return_value = {"active_index_id": "generation", "status": "ready"}
    await tasks.process_document(repository, "doc", "job", 1, 2)
    assert repository.finish.await_count == 1
    remove.assert_awaited_once_with("owner", ["old"])


async def test_unavailable_redis_never_guesses_publication_failed(dependencies):
    repository, _, _, _ = dependencies
    repository.finish.side_effect = ConnectionError()
    repository.internal_document.side_effect = ConnectionError()
    with pytest.raises(ConnectionError):
        await tasks.process_document(repository, "doc", "job", 1, 2)
    assert repository.finish.await_count == 1


async def test_delete_retries_both_external_deletions(attempt, dependencies):
    repository, index, remove, delete = dependencies
    attempt["kind"] = "delete"
    delete.side_effect = [ConnectionError(), None]
    with pytest.raises(ConnectionError):
        await tasks.process_document(repository, "doc", "job", 1, 2)
    await tasks.process_document(repository, "doc", "job", 2, 1)
    assert remove.await_count == 2
    remove.assert_awaited_with("owner", ["old", "generation"])
    repository.finish.assert_awaited_with(attempt)
    index.assert_not_awaited()


def test_entrypoint_uses_rq_retry_count(monkeypatch):
    monkeypatch.setattr(tasks, "get_current_job", lambda: SimpleNamespace(id="job", retries_left=1))
    repository = MagicMock()
    monkeypatch.setattr(tasks, "DocumentRepository", lambda config: repository)
    process = AsyncMock()
    monkeypatch.setattr(tasks, "process_document", process)
    tasks.index_document("doc")
    process.assert_awaited_once_with(repository, "doc", "job", 2, 1)
