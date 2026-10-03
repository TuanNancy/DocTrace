"""Exercise real repository + RQ serialization against an isolated fake Redis server.

The Docker verification script separately checks real Redis and Linux RQ processes.
"""
import asyncio
from uuid import uuid4

import fakeredis
from fastapi import HTTPException
import pytest
from redis.client import Pipeline
from redis.exceptions import ConnectionError, WatchError
from rq.job import Job, JobStatus
from rq.serializers import JSONSerializer

from app.core.config import AppConfig
from app.services import document_repository as module
from app.services.job_queue import DocumentQueue


@pytest.fixture
def library(monkeypatch):
    server = fakeredis.FakeServer()
    connection = fakeredis.FakeRedis(server=server)
    monkeypatch.setattr(module.Redis, "from_url", lambda *args, **kwargs: fakeredis.FakeRedis(server=server))
    config = AppConfig()
    return module.DocumentRepository(config), connection, DocumentQueue(config, connection), server


def upload(owner="owner"):
    doc_id = str(uuid4())
    return {"doc_id": doc_id, "user_id": owner, "name": "sample.pdf", "size_bytes": 12,
            "storage_key": f"{owner}/{doc_id}/sample.pdf"}


def job(connection, record, status=None):
    result = Job.fetch(record["job_id"], connection=connection, serializer=JSONSerializer)
    if status:
        result.set_status(status)
    return result


async def test_create_commits_catalog_and_one_json_job_without_ttl(library):
    repository, connection, queue, _ = library
    document = upload()
    records = await asyncio.gather(repository.create(document), repository.create(document))
    assert records[0] == records[1]
    record = records[0]
    assert queue.queue.job_ids == [record["job_id"]]
    queued = job(connection, record)
    assert queued.func_name == "app.jobs.documents.index_document"
    assert queued.args == [document["doc_id"]]
    assert queued.retries_left == 2
    assert connection.ttl(module.document_key(document["doc_id"])) == -1
    assert connection.ttl(module.catalog_key("owner")) == -1
    listed = await repository.list("owner", 100, 0)
    assert listed["items"][0]["status"] == "queued"
    assert "storage_key" not in listed["items"][0]
    assert "job_id" not in listed["items"][0]


async def test_owner_scope_applies_to_reads_listing_and_mutations(library):
    repository, _, _, _ = library
    document = await repository.create(upload())
    for action in (repository.get("other", document["doc_id"]),
                   repository.queue("other", document["doc_id"], "delete")):
        with pytest.raises(HTTPException) as error:
            await action
        assert error.value.status_code == 404
    assert await repository.list("other", 10, 0) == {"items": [], "has_more": False}
    with pytest.raises(HTTPException) as error:
        await repository.get("owner", "invalid-id")
    assert error.value.status_code == 404


async def test_catalog_pagination(library):
    repository, _, _, _ = library
    records = [await repository.create(upload()) for _ in range(3)]
    first = await repository.list("owner", 2, 0)
    second = await repository.list("owner", 2, 2)
    assert [item["doc_id"] for item in first["items"]] == [item["doc_id"] for item in reversed(records[1:])]
    assert first["has_more"] is True
    assert second["has_more"] is False
    assert second["items"][0]["doc_id"] == records[0]["doc_id"]


@pytest.mark.parametrize("state", [JobStatus.QUEUED, JobStatus.STARTED, JobStatus.SCHEDULED, JobStatus.DEFERRED])
async def test_active_rq_job_blocks_delete_and_retry(library, state):
    repository, connection, _, _ = library
    document = await repository.create(upload())
    job(connection, document, state)
    for kind in ("index", "delete"):
        with pytest.raises(HTTPException) as error:
            await repository.queue("owner", document["doc_id"], kind)
        assert error.value.status_code == 409


@pytest.mark.parametrize("state", [JobStatus.FAILED, JobStatus.STOPPED, JobStatus.CANCELED, JobStatus.FINISHED, None])
async def test_pre_task_failure_or_missing_job_becomes_retryable_business_error(library, state):
    repository, connection, _, _ = library
    document = await repository.create(upload())
    if state:
        job(connection, document, state)
    else:
        connection.delete(Job.key_for(document["job_id"]))
    current = await repository.get("owner", document["doc_id"])
    assert current["status"] == "error"
    assert current["error"]
    retried = await repository.queue("owner", document["doc_id"], "index")
    assert retried["job_id"] != document["job_id"]
    assert retried["status"] == "queued"
    assert await repository.begin(document["doc_id"], document["job_id"], 1) is None


async def test_concurrent_retry_enqueues_only_one_replacement(library):
    repository, connection, queue, _ = library
    document = await repository.create(upload())
    job(connection, document, JobStatus.FAILED)
    results = await asyncio.gather(*[repository.queue("owner", document["doc_id"], "index") for _ in range(2)],
                                   return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1
    assert sum(isinstance(result, HTTPException) and result.status_code == 409 for result in results) == 1
    assert queue.queue.count == 2  # Initial job + exactly one new retry job.


async def test_attempt_fencing_and_business_success_survive_job_expiry(library):
    repository, connection, _, _ = library
    document = await repository.create(upload())
    first = await repository.begin(document["doc_id"], document["job_id"], 1)
    assert await repository.begin(document["doc_id"], document["job_id"], 1) is None
    second = await repository.begin(document["doc_id"], document["job_id"], 2)
    assert second["attempt_id"] != first["attempt_id"]
    assert await repository.finish(first, chunks_count=99) is False
    assert await repository.finish(second, chunks_count=3) is True
    assert await repository.finish(second, error="late failure") is False
    connection.delete(Job.key_for(document["job_id"]))
    current = await repository.get("owner", document["doc_id"])
    assert current["status"] == "ready"
    assert current["active_index_id"] == second["attempt_id"]
    assert current["chunks_count"] == 3


async def test_invalid_pdf_remains_error_when_rq_reports_finished(library):
    repository, connection, _, _ = library
    document = await repository.create(upload())
    attempt = await repository.begin(document["doc_id"], document["job_id"], 1)
    await repository.finish(attempt, error="Invalid PDF")
    job(connection, document, JobStatus.FINISHED)
    assert (await repository.get("owner", document["doc_id"]))["status"] == "error"


async def test_delete_revokes_index_and_retries_deletion_intent(library):
    repository, connection, _, _ = library
    document = await repository.create(upload())
    attempt = await repository.begin(document["doc_id"], document["job_id"], 1)
    await repository.finish(attempt, chunks_count=3)
    job(connection, document, JobStatus.FINISHED)
    deleting = await repository.queue("owner", document["doc_id"], "delete")
    assert deleting["active_index_id"] is None
    assert deleting["generations"] == [attempt["attempt_id"]]
    deletion = await repository.begin(document["doc_id"], deleting["job_id"], 1)
    await repository.finish(deletion, error="Storage unavailable")
    job(connection, deleting, JobStatus.FAILED)
    with pytest.raises(HTTPException):
        await repository.queue("owner", document["doc_id"], "index")
    retried = await repository.queue("owner", document["doc_id"], "delete")
    await repository.finish(await repository.begin(document["doc_id"], retried["job_id"], 1))
    assert await repository.list("owner", 10, 0) == {"items": [], "has_more": False}
    with pytest.raises(HTTPException) as error:
        await repository.get("owner", document["doc_id"])
    assert error.value.status_code == 404
    assert (await repository.internal_document(document["doc_id"]))["status"] == "deleted"


async def test_redis_outage_never_looks_like_an_empty_library(library):
    repository, _, _, server = library
    server.connected = False
    with pytest.raises(HTTPException) as error:
        await repository.list("owner", 10, 0)
    assert error.value.status_code == 503


async def test_watch_conflict_cannot_enqueue_outside_the_catalog_transaction(library, monkeypatch):
    repository, connection, queue, _ = library
    enqueue = DocumentQueue.enqueue
    calls = 0

    def conflict(self, doc_id, job_id, kind, pipeline):
        nonlocal calls
        enqueue(self, doc_id, job_id, kind, pipeline)
        calls += 1
        if calls == 1:
            connection.hset(module.document_key(doc_id), "conflict", "1")

    monkeypatch.setattr(DocumentQueue, "enqueue", conflict)
    document = await repository.create(upload())
    assert calls == 2
    assert queue.queue.job_ids == [document["job_id"]]
    assert (await repository.get("owner", document["doc_id"]))["status"] == "queued"


@pytest.mark.parametrize("exception", [ConnectionError, WatchError])
async def test_lost_retry_exec_reply_returns_the_committed_job(library, monkeypatch, exception):
    repository, connection, queue, _ = library
    document = await repository.create(upload())
    attempt = await repository.begin(document["doc_id"], document["job_id"], 1)
    await repository.finish(attempt, error="failed")
    job(connection, document, JobStatus.FAILED)
    execute = Pipeline.execute
    lost = False

    def lose_reply(self, *args, **kwargs):
        nonlocal lost
        enqueue = any(command[0][0] == "RPUSH" for command in self.command_stack)
        result = execute(self, *args, **kwargs)
        if enqueue and not lost:
            lost = True
            raise exception("EXEC committed, reply lost")
        return result

    monkeypatch.setattr(Pipeline, "execute", lose_reply)
    retried = await repository.queue("owner", document["doc_id"], "index")
    assert lost
    assert retried["status"] == "queued"
    assert queue.queue.job_ids.count(retried["job_id"]) == 1
