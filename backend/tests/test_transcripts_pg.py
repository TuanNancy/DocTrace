"""Transcript persistence, scoping and retention against real Postgres.

The P0 schema already contains conversations/messages; P3 adds no migration.
These tests exercise the admission transaction, owner scoping, stale citation
snapshots and both document-deletion retention modes.
"""
import asyncio
from datetime import datetime
from pathlib import Path
from threading import Event
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
import pytest
import fakeredis
from rq.job import Job, JobStatus
from rq.serializers import JSONSerializer
from sqlalchemy import create_engine, text

from app import db
from app.core.config import AppConfig
from app.jobs import documents as tasks
from app.services import document_repository as catalog_module
from app.services.document_repository import DocumentRepository
from app.services.quotas import QuotaService
from app.services.transcripts import TranscriptService, purge_expired_transcripts, stale_sources

BACKEND = Path(__file__).resolve().parents[1]


def _docker_available() -> bool:
    try:
        import docker

        client = docker.from_env(timeout=2)
        try:
            return client.ping()
        finally:
            client.close()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _docker_available(), reason="Transcript integration tests require a running Docker daemon",
)


@pytest.fixture(scope="module")
def postgres_url():
    from testcontainers.postgres import PostgresContainer

    container = PostgresContainer("postgres:16-alpine", driver="psycopg")
    container.start()
    try:
        url = container.get_connection_url()
        config = Config(str(BACKEND / "alembic.ini"))
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "head")
        yield url
    finally:
        container.stop()


@pytest.fixture
def quotas(postgres_url, repository):
    db.dispose_engines()
    yield QuotaService(AppConfig(database_url=postgres_url), repository=repository)
    db.dispose_engines()


@pytest.fixture
def transcripts(postgres_url):
    db.dispose_engines()
    yield TranscriptService(AppConfig(database_url=postgres_url))
    db.dispose_engines()


@pytest.fixture
def catalog(postgres_url, monkeypatch):
    server = fakeredis.FakeServer()
    monkeypatch.setattr(catalog_module.Redis, "from_url", lambda *a, **kw: fakeredis.FakeRedis(server=server))
    config = AppConfig(database_url=postgres_url)
    return DocumentRepository(config), fakeredis.FakeRedis(server=server)


def execute(postgres_url, statement, params=None):
    engine = create_engine(postgres_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(statement), params or {})
    finally:
        engine.dispose()


def scalar(postgres_url, statement, params=None):
    engine = create_engine(postgres_url)
    try:
        with engine.connect() as connection:
            return connection.execute(text(statement), params or {}).scalar()
    finally:
        engine.dispose()


def create_workspace(postgres_url, plan="free"):
    workspace_id = str(uuid4())
    execute(
        postgres_url,
        "insert into doctrace.workspaces (id, name, kind, plan, created_by) "
        "values (:id, 'Nhóm', 'team', :plan, :id)",
        {"id": workspace_id, "plan": plan},
    )
    return workspace_id


async def flow(quotas, workspace_id, user_id, doc_id, *, plan="free", query="Câu hỏi"):
    return await quotas.admit_chat(
        workspace_id, user_id, str(uuid4()), doc_id, plan,
        query=query, index_id=doc_id,
    )


def counts(postgres_url, workspace_id):
    return (
        scalar(
            postgres_url,
            "select count(*) from doctrace.conversations where workspace_id = :workspace",
            {"workspace": workspace_id},
        ),
        scalar(
            postgres_url,
            "select count(*) from doctrace.messages m "
            "join doctrace.conversations c on c.id = m.conversation_id "
            "where c.workspace_id = :workspace",
            {"workspace": workspace_id},
        ),
    )


async def test_admission_creates_one_conversation_with_ordered_messages(
    quotas, transcripts, postgres_url,
):
    workspace_id = create_workspace(postgres_url)
    user_id = str(uuid4())
    doc_id = str(uuid4())

    first = await flow(quotas, workspace_id, user_id, doc_id, query="Câu hỏi 1")
    assert first["conversation_id"]
    assert first["assistant_message_id"]
    assert scalar(
        postgres_url,
        "select conversation_id::text from doctrace.chat_requests where id = cast(:id as uuid)",
        {"id": first["chat_request_id"]},
    ) == first["conversation_id"]

    conversation = await transcripts.get(workspace_id, user_id, first["conversation_id"])
    assert [message["role"] for message in conversation["messages"]] == ["user", "assistant"]
    assert conversation["messages"][0]["content"] == "Câu hỏi 1"
    assert conversation["messages"][1]["status"] == "pending"
    assert conversation["messages"][1]["index_id"] == doc_id

    sources = [{
        "citation_id": 1, "chunk_id": str(uuid4()), "doc_id": doc_id,
        "page": 3, "source": "sample.pdf", "score": 0.87,
    }]
    assert await transcripts.mark_streaming(first["assistant_message_id"]) is True
    assert await transcripts.finalize_message(
        first["assistant_message_id"], "complete", "Câu trả lời 1", sources,
    ) is True
    assert await transcripts.finalize_message(
        first["assistant_message_id"], "complete", "Không ghi đè", [],
    ) is False

    conversation = await transcripts.get(workspace_id, user_id, first["conversation_id"])
    assistant = conversation["messages"][1]
    assert (assistant["status"], assistant["content"]) == ("complete", "Câu trả lời 1")
    assert assistant["sources"][0]["chunk_id"] == sources[0]["chunk_id"]

    second = await flow(quotas, workspace_id, user_id, doc_id, query="Câu hỏi 2")
    assert second["conversation_id"] == first["conversation_id"]
    conversation = await transcripts.get(workspace_id, user_id, first["conversation_id"])
    assert [message["role"] for message in conversation["messages"]] == [
        "user", "assistant", "user", "assistant",
    ]
    assert [message["content"] for message in conversation["messages"][:3]] == [
        "Câu hỏi 1", "Câu trả lời 1", "Câu hỏi 2",
    ]
    assert counts(postgres_url, workspace_id) == (1, 4)


async def test_duplicate_request_does_not_duplicate_messages(quotas, transcripts, postgres_url):
    workspace_id = create_workspace(postgres_url)
    user_id = str(uuid4())
    doc_id = str(uuid4())
    request_id = str(uuid4())

    first = await quotas.admit_chat(
        workspace_id, user_id, request_id, doc_id, "free",
        query="Một lần", index_id=doc_id,
    )
    with pytest.raises(HTTPException) as caught:
        await quotas.admit_chat(
            workspace_id, user_id, request_id, doc_id, "free",
            query="Một lần", index_id=doc_id,
        )
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "request_in_progress"
    assert caught.value.detail["chat_request_id"] == first["chat_request_id"]
    assert counts(postgres_url, workspace_id) == (1, 2)
    assert scalar(
        postgres_url,
        "select used from doctrace.usage_counters "
        "where workspace_id = :workspace and metric = 'chat_questions_month'",
        {"workspace": workspace_id},
    ) == 1


async def test_transcripts_are_scoped_to_workspace_and_owner(quotas, transcripts, postgres_url):
    workspace_id = create_workspace(postgres_url)
    other_workspace = create_workspace(postgres_url)
    owner = str(uuid4())
    member = str(uuid4())
    doc_id = str(uuid4())
    admission = await flow(quotas, workspace_id, owner, doc_id)
    conversation_id = admission["conversation_id"]

    assert await transcripts.get(workspace_id, owner, conversation_id) is not None
    assert await transcripts.get(workspace_id, member, conversation_id) is None
    assert await transcripts.get(other_workspace, owner, conversation_id) is None
    assert await transcripts.delete(workspace_id, member, conversation_id) is False
    assert await transcripts.delete(other_workspace, owner, conversation_id) is False

    assert (await transcripts.list(workspace_id, member))["items"] == []
    assert (await transcripts.list(other_workspace, owner))["items"] == []
    listing = await transcripts.list(workspace_id, owner)
    assert [item["id"] for item in listing["items"]] == [conversation_id]
    assert listing["items"][0]["doc_id"] == doc_id
    assert listing["items"][0]["message_count"] == 2

    # A second document keeps only the requested conversation when filtered.
    other_doc = str(uuid4())
    second = await flow(quotas, workspace_id, owner, other_doc)
    filtered = await transcripts.list(workspace_id, owner, doc_id=doc_id)
    assert [item["id"] for item in filtered["items"]] == [conversation_id]
    assert second["conversation_id"] != conversation_id


async def test_retain_mode_hides_then_purges_without_deleting_cost_rows(
    quotas, transcripts, postgres_url,
):
    workspace_id = create_workspace(postgres_url)
    user_id = str(uuid4())
    doc_id = str(uuid4())
    admission = await flow(quotas, workspace_id, user_id, doc_id)
    execute(
        postgres_url,
        "insert into doctrace.provider_calls "
        "(workspace_id, user_id, doc_id, request_id, kind, model, cost_micros, cost_status) "
        "values (:workspace, :user, :doc, :request, 'answer', 'test-model', 1000, 'reported')",
        {
            "workspace": workspace_id, "user": user_id, "doc": doc_id,
            "request": admission["request_id"],
        },
    )

    assert await transcripts.hide_for_document(workspace_id, user_id, doc_id) == 1
    hidden = await transcripts.list(workspace_id, user_id)
    assert hidden["items"] == []
    assert await transcripts.get(workspace_id, user_id, admission["conversation_id"]) is None
    assert scalar(
        postgres_url,
        "select (document_deleted_at is not null and purge_after > now()) "
        "from doctrace.conversations where id = cast(:id as uuid)",
        {"id": admission["conversation_id"]},
    ) is True
    # Retain mode keeps the content until the purge boundary.
    assert counts(postgres_url, workspace_id) == (1, 2)
    assert await transcripts.finalize_message(
        admission["assistant_message_id"], "complete", "Late content", [],
    ) is False

    # A retry must not extend the retention window.
    assert await transcripts.hide_for_document(workspace_id, user_id, doc_id) == 0

    execute(
        postgres_url,
        "update doctrace.conversations set purge_after = now() - interval '1 minute' "
        "where id = cast(:id as uuid)",
        {"id": admission["conversation_id"]},
    )
    config = AppConfig(database_url=postgres_url)
    assert purge_expired_transcripts(config) == 1
    assert counts(postgres_url, workspace_id) == (0, 0)
    assert scalar(
        postgres_url,
        "select count(*) from doctrace.provider_calls where workspace_id = :workspace",
        {"workspace": workspace_id},
    ) == 1


async def test_cascade_mode_deletes_content_immediately(quotas, postgres_url):
    workspace_id = create_workspace(postgres_url)
    user_id = str(uuid4())
    doc_id = str(uuid4())
    admission = await flow(quotas, workspace_id, user_id, doc_id)
    config = AppConfig(database_url=postgres_url, transcript_delete_mode="cascade")
    transcripts = TranscriptService(config)

    assert await transcripts.hide_for_document(workspace_id, user_id, doc_id) == 1
    assert counts(postgres_url, workspace_id) == (0, 0)
    assert await transcripts.get(workspace_id, user_id, admission["conversation_id"]) is None


def test_stale_snapshot_compares_the_generation_not_the_chunk_id():
    conversation = {
        "messages": [
            {"role": "user", "content": "q", "sources": []},
            {"role": "assistant", "index_id": "generation-a", "sources": [
                {"chunk_id": "old-chunk", "page": 1},
            ]},
        ],
    }
    marked = stale_sources(conversation, "generation-b")
    assert marked["messages"][1]["stale"] is True
    assert marked["messages"][1]["sources"][0]["stale"] is True
    marked = stale_sources(conversation, "generation-a")
    assert marked["messages"][1]["stale"] is False
    assert marked["messages"][1]["sources"][0]["stale"] is False
    marked = stale_sources(conversation, None)
    assert marked["messages"][1]["sources"][0]["stale"] is True


async def ready_document(catalog, postgres_url):
    repository, redis = catalog
    workspace, user, doc_id = create_workspace(postgres_url), str(uuid4()), str(uuid4())
    document = await repository.create({
        "workspace_id": workspace, "owner_user_id": user, "doc_id": doc_id,
        "name": "fixture.pdf", "size_bytes": 12, "storage_key": "fixture.pdf",
    }, limit=5)
    attempt = await repository.begin(doc_id, document["job_id"], 1)
    await repository.finish(attempt, chunks_count=1)
    Job.fetch(document["job_id"], connection=redis, serializer=JSONSerializer).set_status(JobStatus.FINISHED)
    return workspace, user, doc_id


async def wait_for_document_lock(postgres_url):
    engine = create_engine(postgres_url)
    try:
        for _ in range(200):
            with engine.connect() as connection:
                waiting = connection.execute(text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' AND query LIKE '%pg_advisory_xact_lock%'"
                )).scalar_one()
            if waiting:
                return
            await asyncio.sleep(0.01)
        pytest.fail("Competing operation never waited on the document fence")
    finally:
        engine.dispose()


@pytest.mark.parametrize("mode", ["retain_30d", "cascade"])
@pytest.mark.parametrize("reason", ["busy", "foreign", "wrong_workspace"])
async def test_rejected_deletion_preserves_transcript(catalog, postgres_url, mode, reason):
    repository, redis = catalog
    workspace, user, doc_id = await ready_document(catalog, postgres_url)
    quotas = QuotaService(repository.config, repository)
    admission = await quotas.admit_chat(workspace, user, str(uuid4()), doc_id, "free")
    transcripts = TranscriptService(AppConfig(database_url=postgres_url, transcript_delete_mode=mode))
    document = await repository.get(workspace, user, doc_id)
    if reason == "busy":
        Job.fetch(document["job_id"], connection=redis, serializer=JSONSerializer).set_status(JobStatus.STARTED)
    with pytest.raises(HTTPException) as caught:
        await transcripts.queue_document_deletion(
            str(uuid4()) if reason == "wrong_workspace" else workspace,
            str(uuid4()) if reason == "foreign" else user, doc_id, repository,
        )
    assert caught.value.status_code == (409 if reason == "busy" else 404)
    saved = await transcripts.get(workspace, user, admission["conversation_id"])
    assert len(saved["messages"]) == 2
    assert not (await repository.internal_document(doc_id)).get("delete_requested_at")


@pytest.mark.parametrize("mode", ["retain_30d", "cascade"])
@pytest.mark.parametrize("first", ["chat", "delete"])
async def test_chat_and_delete_share_a_document_fence(catalog, postgres_url, monkeypatch, mode, first):
    repository, _ = catalog
    workspace, user, doc_id = await ready_document(catalog, postgres_url)
    quotas = QuotaService(repository.config, repository)
    await quotas.admit_chat(workspace, user, str(uuid4()), doc_id, "free", query="Saved")
    transcripts = TranscriptService(AppConfig(database_url=postgres_url, transcript_delete_mode=mode))
    entered, release = Event(), Event()
    method = "get_sync" if first == "chat" else "queue_sync"
    original = getattr(repository, method)

    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(repository, method, blocked)
    actions = {
        "chat": lambda: quotas.admit_chat(workspace, user, str(uuid4()), doc_id, "free", query="Race"),
        "delete": lambda: transcripts.queue_document_deletion(workspace, user, doc_id, repository),
    }
    leading = asyncio.create_task(actions[first]())
    assert await asyncio.to_thread(entered.wait, 5)
    trailing = asyncio.create_task(actions["delete" if first == "chat" else "chat"]())
    try:
        await wait_for_document_lock(postgres_url)
    finally:
        release.set()
        results = await asyncio.gather(leading, trailing, return_exceptions=True)
    if first == "delete":
        assert results[0]["status"] == "deleting"
        assert isinstance(results[1], HTTPException) and results[1].status_code == 409
    else:
        assert results[0]["conversation_id"]
        assert results[1]["status"] == "deleting"
    assert (await transcripts.list(workspace, user))["items"] == []
    assert await repository.transcript_documents(workspace, user, [doc_id]) == {}
    assert scalar(postgres_url, "select used from doctrace.usage_counters where workspace_id = :w",
                  {"w": workspace}) == (2 if first == "chat" else 1)
    assert counts(postgres_url, workspace) == ((0, 0) if mode == "cascade" else (1, 4 if first == "chat" else 2))


@pytest.mark.parametrize("mode", ["retain_30d", "cascade"])
async def test_worker_recovers_sql_rollback_after_redis_delete_commit(catalog, postgres_url, monkeypatch, mode):
    repository, _ = catalog
    workspace, user, doc_id = await ready_document(catalog, postgres_url)
    quotas = QuotaService(repository.config, repository)
    await quotas.admit_chat(workspace, user, str(uuid4()), doc_id, "free", query="Private content")
    repository.config = AppConfig(database_url=postgres_url, transcript_delete_mode=mode)
    transcripts = TranscriptService(repository.config)
    original = transcripts._queue_document_deletion

    def lost_commit(*args):
        original(*args)
        raise RuntimeError("SQL transaction rolled back after Redis committed")

    monkeypatch.setattr(transcripts, "_queue_document_deletion", lost_commit)
    with pytest.raises(HTTPException) as caught:
        await transcripts.queue_document_deletion(workspace, user, doc_id, repository)
    assert caught.value.status_code == 503
    assert counts(postgres_url, workspace) == (1, 2)
    deleting = await repository.internal_document(doc_id)
    assert deleting["status"] == "deleting"
    assert await repository.transcript_documents(workspace, user, [doc_id]) == {}
    with pytest.raises(HTTPException) as caught:
        await quotas.admit_chat(workspace, user, str(uuid4()), doc_id, "free")
    assert caught.value.status_code == 409

    remove, delete = AsyncMock(), MagicMock()
    monkeypatch.setattr(tasks, "remove_generations", remove)
    monkeypatch.setattr(tasks, "delete_pdf", delete)
    await tasks.process_document(repository, doc_id, deleting["job_id"], 1, 2)
    assert (await repository.internal_document(doc_id))["status"] == "deleted"
    assert (await transcripts.list(workspace, user))["items"] == []
    assert counts(postgres_url, workspace) == ((0, 0) if mode == "cascade" else (1, 2))
    if mode == "retain_30d":
        accepted = datetime.fromisoformat(deleting["delete_requested_at"])
        assert scalar(postgres_url, "select document_deleted_at from doctrace.conversations where doc_id = :d",
                      {"d": doc_id}) == accepted
    remove.assert_awaited_once()
    delete.assert_called_once()
