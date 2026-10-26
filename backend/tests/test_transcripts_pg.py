"""Transcript persistence, scoping and retention against real Postgres.

The P0 schema already contains conversations/messages; P3 adds no migration.
These tests exercise the admission transaction, owner scoping, stale citation
snapshots and both document-deletion retention modes.
"""
from pathlib import Path
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi import HTTPException
import pytest
from sqlalchemy import create_engine, text

from app import db
from app.core.config import AppConfig
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
def quotas(postgres_url):
    db.dispose_engines()
    yield QuotaService(AppConfig(database_url=postgres_url))
    db.dispose_engines()


@pytest.fixture
def transcripts(postgres_url):
    db.dispose_engines()
    yield TranscriptService(AppConfig(database_url=postgres_url))
    db.dispose_engines()


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
