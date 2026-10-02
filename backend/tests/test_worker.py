from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app import worker


@pytest.fixture
def job():
    return {"job_id": "job", "kind": "index", "lease_token": "new-generation", "document": {
        "doc_id": "doc", "user_id": "owner", "name": "file.pdf", "storage_key": "owner/doc/file.pdf",
    }}


@pytest.fixture
def dependencies(monkeypatch):
    repository = AsyncMock()
    repository.finish.return_value = True
    repository.get.return_value = {"active_index_id": None}
    repository.generations.return_value = ["old-generation", "new-generation"]
    index = AsyncMock(return_value=SimpleNamespace(chunks_count=3, warnings=[]))
    remove = AsyncMock()
    delete = MagicMock()
    monkeypatch.setattr(worker, "index_pdf_bytes", index)
    monkeypatch.setattr(worker, "download_pdf", MagicMock(return_value=b"%PDF-1.4"))
    monkeypatch.setattr(worker, "delete_pdf", delete)
    monkeypatch.setattr(worker, "remove_generations", remove)
    return repository, index, remove, delete


async def test_index_is_staged_then_published_and_old_generations_cleaned(job, dependencies):
    repository, index, remove, _ = dependencies
    await worker.process_job(repository, job)
    index.assert_awaited_once_with(b"%PDF-1.4", "file.pdf", "new-generation", user_id="owner")
    repository.finish.assert_awaited_once_with(job, chunks_count=3, warnings=[])
    remove.assert_awaited_once_with("owner", ["old-generation"])


async def test_expired_worker_cannot_leave_its_generation_published(job, dependencies):
    repository, _, remove, _ = dependencies
    repository.finish.return_value = False
    await worker.process_job(repository, job)
    remove.assert_awaited_once_with("owner", ["new-generation"])


async def test_lost_finish_response_does_not_delete_committed_index(job, dependencies):
    repository, _, remove, _ = dependencies
    repository.finish.side_effect = [ConnectionError("response lost"), False]
    repository.get.return_value = {"active_index_id": "new-generation"}
    await worker.process_job(repository, job)
    remove.assert_not_awaited()


async def test_partial_index_failure_is_cleaned_and_persisted(job, dependencies):
    repository, index, remove, _ = dependencies
    index.side_effect = RuntimeError("embedding secret")
    await worker.process_job(repository, job)
    assert "embedding secret" not in repository.finish.call_args.kwargs["error"]
    remove.assert_awaited_once_with("owner", ["new-generation"])


async def test_delete_failure_remains_retryable_and_repeats_idempotent_cleanup(job, dependencies):
    repository, index, remove, delete = dependencies
    job["kind"] = "delete"
    delete.side_effect = [RuntimeError("S3 down"), None]
    await worker.process_job(repository, job)
    assert repository.finish.call_args.kwargs["error"]
    await worker.process_job(repository, job)
    assert repository.finish.call_args.kwargs == {}
    assert remove.await_count == 2
    index.assert_not_awaited()


async def test_tombstone_sweep_removes_late_remote_writes_without_republishing(job, dependencies):
    repository, index, remove, delete = dependencies
    repository.tombstones_due.return_value = [job["document"]]
    await worker.sweep_tombstones(repository)
    remove.assert_awaited_once_with("owner", ["old-generation", "new-generation"])
    delete.assert_called_once_with("owner/doc/file.pdf")
    repository.tombstone_cleaned.assert_awaited_once_with("doc")
    repository.finish.assert_not_awaited()
    index.assert_not_awaited()
