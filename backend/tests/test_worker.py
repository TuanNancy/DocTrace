from contextlib import contextmanager
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.jobs import documents as tasks
from app.services import provider_calls
from app.services.pdf_indexing import InvalidPDFError
from app.core.observability import JsonFormatter, current_request_id, log_context


@pytest.fixture
def attempt():
    return {"job_id": "job", "attempt_id": "generation", "kind": "index", "document": {
        "doc_id": "doc", "user_id": "owner", "name": "original.pdf", "storage_key": "owner/doc/original.pdf",
        "generations": ["old", "generation"],
    }}


@pytest.fixture
def dependencies(monkeypatch, attempt):
    repository = AsyncMock()
    from app.core.config import AppConfig
    repository.config = AppConfig()
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
    monkeypatch.setattr(tasks, "TranscriptService", MagicMock(return_value=AsyncMock()))
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


async def test_index_job_records_embedding_usage_with_workspace_attribution(
    attempt, dependencies, monkeypatch,
):
    repository, index, _, _ = dependencies
    workspace = str(uuid4())
    attempt["document"]["workspace_id"] = workspace
    captured = []

    class Session:
        def execute(self, statement, rows):
            captured.extend(rows)

    @contextmanager
    def scope(config):
        yield Session()

    monkeypatch.setattr(provider_calls, "get_config", lambda: SimpleNamespace(
        database_url="postgresql://example.test/doctrace", openrouter_api_key=None,
    ))
    monkeypatch.setattr(provider_calls, "session_scope", scope)

    async def fake_index(content, name, generation, *, user_id, usage=None):
        assert usage is not None
        call = usage.start("index_embedding", "embedding-model")
        assert call is not None
        call.apply_usage({"prompt_tokens": 12, "cost": "0.000004"})
        return SimpleNamespace(chunks_count=3, warnings=[])

    index.side_effect = fake_index

    await tasks.process_document(repository, "doc", "job", 1, 0)

    assert len(captured) == 1
    row = captured[0]
    assert row["kind"] == "index_embedding"
    assert row["workspace_id"] == workspace
    assert row["user_id"] is None
    assert row["doc_id"] is None
    assert row["job_id"] == "job"
    assert row["prompt_tokens"] == 12
    assert row["cost_micros"] == 4
    assert row["cost_status"] == "reported"


async def test_delete_job_never_creates_usage_rows(attempt, dependencies, monkeypatch):
    repository, _, remove, delete = dependencies
    attempt["kind"] = "delete"
    monkeypatch.setattr(provider_calls, "get_config", lambda: SimpleNamespace(
        database_url="postgresql://example.test/doctrace", openrouter_api_key=None,
    ))
    store = MagicMock()
    monkeypatch.setattr(provider_calls.UsageCollector, "_store", store)

    await tasks.process_document(repository, "doc", "job", 1, 0)

    store.assert_not_called()
    remove.assert_awaited_once()
    delete.assert_called_once()


async def test_delete_waits_for_transcript_recovery_before_external_cleanup(attempt, dependencies):
    repository, _, remove, delete = dependencies
    attempt["kind"] = "delete"
    attempt["document"].update(workspace_id="workspace", delete_requested_at="2026-10-28T00:00:00Z")
    transcripts = tasks.TranscriptService.return_value
    transcripts.hide_for_document.side_effect = ConnectionError("Postgres unavailable")
    with pytest.raises(ConnectionError):
        await tasks.process_document(repository, "doc", "job", 1, 2)
    transcripts.hide_for_document.assert_awaited_once_with(
        "workspace", "owner", "doc", deleted_at="2026-10-28T00:00:00Z",
    )
    remove.assert_not_awaited()
    delete.assert_not_called()
    assert repository.finish.call_args.kwargs["retryable"] is True


async def test_worker_binds_context_through_blocking_calls_and_resets_it(attempt, dependencies, monkeypatch, caplog):
    repository, index, _, _ = dependencies
    attempt["document"].update(request_id="original-upload", workspace_id="workspace")
    captured = []

    def download(key):
        assert current_request_id() == "original-upload"
        record = logging.LogRecord("app.jobs.documents", logging.INFO, __file__, 1, "document_job_started", (), None)
        captured.append(json.loads(JsonFormatter().format(record)))
        return b"pdf"

    monkeypatch.setattr(tasks, "download_pdf", download)
    index.side_effect = ConnectionError("secret-upstream-body")
    with caplog.at_level(logging.INFO, logger="app.jobs.documents"):
        with pytest.raises(ConnectionError):
            await tasks.process_document(repository, "doc", "job", 2, 1)
    assert captured[0]["request_id"] == "original-upload"
    assert captured[0]["workspace_id"] == "workspace"
    assert captured[0]["job_id"] == "job"
    assert captured[0]["attempt"] == 2
    assert current_request_id() == "-"
    assert log_context.get() == {}


def test_worker_never_persists_raw_rq_exception():
    from fakeredis import FakeRedis
    from rq import Queue
    from rq.job import Job, JobStatus
    from rq.registry import FailedJobRegistry
    from rq.serializers import JSONSerializer
    from app.worker import DocumentWorker

    with FakeRedis() as connection:
        queue = Queue("documents-test", connection=connection, serializer=JSONSerializer)
        job = queue.enqueue("app.jobs.documents.index_document", "doc")
        worker = DocumentWorker([queue], connection=connection, serializer=JSONSerializer)
        worker.handle_job_failure(job, queue, exc_string="private-prompt Bearer secret")

        persisted = Job.fetch(job.id, connection=connection, serializer=JSONSerializer)
        assert persisted.get_status() == JobStatus.FAILED
        assert job.id in FailedJobRegistry(queue=queue).get_job_ids()
        assert persisted.exc_info == "Document job failed; consult structured logs by job_id."
        assert "private-prompt" not in persisted.latest_result().exc_string
        assert "secret" not in persisted.latest_result().exc_string
