"""Team acceptance through HTTP, real Postgres/Redis and an in-process RQ worker.

Only Auth HTTP, retained PDFs and AI/vector operations use local fixtures. All
workspace authorization, catalog mutations, quota, transcripts and metering run
as the unprivileged runtime role. Linux fork/retry behavior is covered separately
by scripts/verify_document_queue.py.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import httpx
import pytest
from redis import Redis
from rq import Queue, SimpleWorker
from rq.serializers import JSONSerializer
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app import db
from app.core import auth, config as config_module
from app.jobs import documents as jobs
from app.main import app
from app.routers import chat, documents, upload
from app.storage.base import RetrievedChunk

BACKEND = Path(__file__).resolve().parents[1]


def _docker_available():
    try:
        import docker

        client = docker.from_env(timeout=2)
        try:
            return client.ping()
        finally:
            client.close()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _docker_available(), reason="Team acceptance requires Docker")


@pytest.fixture(scope="module")
def infrastructure(install_auth_schema):
    from testcontainers.postgres import PostgresContainer
    from testcontainers.redis import RedisContainer

    with PostgresContainer("postgres:16-alpine", driver="psycopg") as postgres:
        with RedisContainer("redis:7.4-alpine") as redis:
            url = postgres.get_connection_url()
            migration_url = install_auth_schema(url)
            admin = create_engine(url)
            try:
                with admin.begin() as connection:
                    connection.exec_driver_sql((BACKEND.parent / "deploy/postgres/bootstrap-runtime-role.sql").read_text())
                    connection.exec_driver_sql("ALTER ROLE doctrace_app PASSWORD 'local-test-only'")
                migration = Config(str(BACKEND / "alembic.ini"))
                migration.set_main_option("sqlalchemy.url", migration_url)
                command.upgrade(migration, "head")
                runtime = make_url(url).set(username="doctrace_app", password="local-test-only")
                yield admin, config_module.AppConfig(
                    database_url=runtime.render_as_string(hide_password=False),
                    redis_url=f"redis://{redis.get_container_host_ip()}:{redis.get_exposed_port(6379)}/0",
                    supabase_url="https://auth.example.test", supabase_publishable_key="fixture-publishable",
                    rate_limit_chat_requests=100, rate_limit_upload_requests=100,
                )
            finally:
                db.dispose_engines()
                admin.dispose()


@pytest.fixture
def team(infrastructure, monkeypatch):
    admin, config = infrastructure
    monkeypatch.setattr(config_module, "_config", config)
    identities = {name: str(uuid4()) for name in ("owner", "member", "admin")}
    with admin.begin() as connection:
        connection.execute(text("INSERT INTO auth.users (id) VALUES (:id)"),
                           [{"id": uid} for uid in identities.values()])
        connection.execute(text("INSERT INTO doctrace.platform_admins (user_id) VALUES (:id)"),
                           {"id": identities["admin"]})

    def authenticate(request):
        assert str(request.url) == "https://auth.example.test/auth/v1/user"
        assert request.headers["apikey"] == "fixture-publishable"
        user = identities.get(request.headers.get("authorization", "").removeprefix("Bearer "))
        return httpx.Response(200, json={"id": user}) if user else httpx.Response(401)

    monkeypatch.setattr(auth, "httpx", SimpleNamespace(
        AsyncClient=lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(authenticate), **kwargs),
        HTTPError=httpx.HTTPError,
    ))
    pdfs, vectors = {}, {}
    monkeypatch.setattr(upload, "is_pdf_storage_configured", lambda: True)
    monkeypatch.setattr(upload, "upload_pdf_to_supabase_storage", lambda data, key: pdfs.__setitem__(key, data))
    monkeypatch.setattr(upload, "delete_pdf", lambda key: pdfs.pop(key, None))
    monkeypatch.setattr(jobs, "download_pdf", lambda key: pdfs[key])
    monkeypatch.setattr(jobs, "delete_pdf", lambda key: pdfs.pop(key, None))

    def signed_link(key):
        assert key in pdfs
        return f"https://pdf.example.test/{key}?token={uuid4()}"

    monkeypatch.setattr(documents, "signed_pdf_url", signed_link)

    async def index_pdf(data, filename, generation, *, user_id, usage):
        vectors[user_id, generation] = RetrievedChunk(
            str(uuid4()), generation, data.decode(), 1, filename, 0.9,
        )
        usage.start("index_embedding", "fixture-embedding").apply_usage({"prompt_tokens": 4, "cost": "0.000010"})
        return SimpleNamespace(chunks_count=1, warnings=[])

    monkeypatch.setattr(jobs, "index_pdf_bytes", index_pdf)

    async def get_chunk(generation, chunk_id, *, user_id):
        chunk = vectors.get((user_id, generation))
        return chunk if chunk and chunk.chunk_id == chunk_id else None

    async def delete_vectors(generation, *, user_id):
        vectors.pop((user_id, generation), None)

    store = SimpleNamespace(get_chunk=get_chunk, delete_document=delete_vectors, disconnect=AsyncMock())
    monkeypatch.setattr(documents, "create_connected_vector_store", AsyncMock(return_value=store))
    monkeypatch.setattr(jobs, "create_connected_vector_store", AsyncMock(return_value=store))

    async def pipeline(*, usage):
        async def retrieve(query, generation, *, user_id):
            return [vectors[user_id, generation]]

        async def answer(*, query, doc_id, user_id, retrieved_chunks_override, **kwargs):
            assert retrieved_chunks_override == [vectors[user_id, doc_id]]
            usage.start("answer", "fixture-answer").apply_usage({
                "prompt_tokens": 5, "completion_tokens": 3, "cost": "0.000025",
            })
            yield f"Answer: {retrieved_chunks_override[0].text} [1]"

        return SimpleNamespace(retrieve_chunks=retrieve, select_context_chunks=lambda chunks: chunks,
                               stream_answer=answer, shutdown=AsyncMock())

    monkeypatch.setattr(chat, "create_initialized_rag_pipeline", pipeline)
    with Redis.from_url(config.redis_url) as redis, TestClient(app) as client:
        queue = Queue(config.rq_queue_name, connection=redis, serializer=JSONSerializer)

        def drain():
            worker = SimpleWorker([queue], connection=redis, serializer=JSONSerializer)
            worker.work(burst=True, logging_level="WARNING")
            assert queue.count == 0
            assert queue.failed_job_registry.count == 0

        def request(who, method, path, *, workspace=None, **kwargs):
            headers = {"Authorization": f"Bearer {who}"}
            if workspace:
                headers["X-Workspace-Id"] = workspace
            return client.request(method, path, headers=headers, **kwargs)

        def upload_document(who, workspace, label):
            response = request(who, "POST", "/api/upload", workspace=workspace,
                               files={"file": (f"{label}.pdf", f"%PDF-1.4 {label}".encode(), "application/pdf")})
            assert response.status_code == 202, response.text
            return response.json()["doc_id"]

        for who in ("owner", "member"):
            personal = request(who, "GET", "/api/workspaces").json()["items"]
            assert personal[0]["id"] == identities[who]
        assert request("owner", "POST", "/api/workspaces", json={"name": "Team"}).status_code == 403
        with admin.begin() as connection:
            connection.execute(text("UPDATE doctrace.workspaces SET plan = 'pro' WHERE id = :id"),
                               {"id": identities["owner"]})
        created = request("owner", "POST", "/api/workspaces", json={"name": "Team"})
        assert created.status_code == 201
        workspace = created.json()["id"]
        assert created.json()["plan"] == "free"
        missing = request("owner", "POST", f"/api/workspaces/{workspace}/members", json={"user_id": str(uuid4())})
        assert missing.status_code == 404 and missing.json()["detail"]["code"] == "member_user_not_found"
        added = request("owner", "POST", f"/api/workspaces/{workspace}/members", json={"user_id": identities["member"]})
        assert added.status_code == 201
        docs = {who: upload_document(who, workspace, f"{who}-private") for who in ("owner", "member")}
        docs["personal"] = upload_document("member", identities["member"], "personal-private")
        drain()
        assert client.get("/ready").status_code == 200
        yield SimpleNamespace(
            client=client, request=request, upload=upload_document, drain=drain, workspace=workspace,
            users=identities, docs=docs, pdfs=pdfs, vectors=vectors, admin=admin,
        )


def ask(team, who, doc_id=None):
    return team.request(who, "POST", "/api/chat", workspace=team.workspace, json={
        "query": f"Question from {who}", "doc_id": doc_id or team.docs[who], "request_id": str(uuid4()),
    })


def test_team_private_documents_transcripts_and_shared_quotas(team):
    request, workspace = team.request, team.workspace
    assert team.client.get("/api/documents", headers={"X-Workspace-Id": workspace}).status_code == 401
    assert request("invalid-token", "GET", "/api/documents", workspace=workspace).status_code == 401
    conversations, chunks = {}, {}
    for who in ("owner", "member"):
        listing = request(who, "GET", "/api/documents", workspace=workspace).json()
        assert [row["doc_id"] for row in listing["items"]] == [team.docs[who]]
        assert listing["items"][0]["status"] == "ready"
        response = ask(team, who)
        assert response.status_code == 200 and "event: done" in response.text
        assert f"{who}-private" in response.text and "personal-private" not in response.text
        conversations[who] = response.headers["X-Conversation-Id"]
        restored = request(who, "GET", f"/api/conversations/{conversations[who]}", workspace=workspace).json()
        assert restored["messages"][1]["status"] == "complete"
        assert f"{who}-private" in restored["messages"][1]["content"]
        source = restored["messages"][1]["sources"][0]
        assert source["stale"] is False
        chunks[who] = source["chunk_id"]
        assert [row["id"] for row in request(who, "GET", "/api/conversations", workspace=workspace).json()["items"]] == [conversations[who]]
        opened = request(who, "GET", f"/api/documents/{team.docs[who]}/chunks/{chunks[who]}", workspace=workspace)
        assert opened.status_code == 200 and f"{who}-private" in opened.json()["text"]
        link = request(who, "GET", f"/api/documents/{team.docs[who]}/file", workspace=workspace).json()
        fresh = request(who, "GET", f"/api/documents/{team.docs[who]}/file", workspace=workspace).json()
        assert link["expires_in"] == 300 and link["url"] != fresh["url"]

    for who, other in (("owner", "member"), ("member", "owner"), ("admin", "member")):
        doc, conversation = team.docs[other], conversations[other]
        for method, path in (
            ("GET", f"/api/documents/{doc}"), ("GET", f"/api/documents/{doc}/file"),
            ("GET", f"/api/documents/{doc}/chunks/{chunks[other]}"),
            ("POST", f"/api/documents/{doc}/retry"), ("DELETE", f"/api/documents/{doc}"),
            ("GET", f"/api/conversations/{conversation}"), ("DELETE", f"/api/conversations/{conversation}"),
        ):
            assert request(who, method, path, workspace=workspace).status_code == 404
        assert ask(team, who, doc).status_code == 404
    # A different workspace cannot reveal even this user's own private PDF.
    assert request("member", "GET", f"/api/documents/{team.docs['personal']}", workspace=workspace).status_code == 404
    assert request("member", "GET", f"/api/conversations/{conversations['member']}", workspace=team.users["member"]).status_code == 404
    assert request("member", "GET", f"/api/workspaces/{workspace}/members").status_code == 404

    owner_usage = request("owner", "GET", "/api/usage", workspace=workspace).json()
    member_usage = request("member", "GET", "/api/usage", workspace=workspace).json()
    assert owner_usage["scope"] == "workspace" and owner_usage["chat"]["used"] == 2
    assert owner_usage["documents"]["used"] == 2
    assert owner_usage["costs"] == {"known_micros": 70, "unknown_calls": 0}
    assert {row["user_id"] for row in owner_usage["by_user"]} == {team.users["owner"], team.users["member"]}
    assert member_usage["scope"] == "self" and member_usage["chat"]["used"] == 1
    assert member_usage["documents"]["used"] == 1
    assert member_usage["chat"]["remaining"] is None and member_usage["documents"]["remaining"] is None
    assert member_usage["costs"] == {"known_micros": 35, "unknown_calls": 0}
    assert [row["user_id"] for row in member_usage["by_user"]] == [team.users["member"]]

    for number, who in enumerate(("owner", "member", "owner")):
        team.upload(who, workspace, f"extra-{number}")
    retained = len(team.pdfs)
    for who in ("owner", "member"):
        denied = request(who, "POST", "/api/upload", workspace=workspace,
                         files={"file": ("over-limit.pdf", b"%PDF-1.4 rejected", "application/pdf")})
        assert denied.status_code == 429 and denied.json()["detail"]["metric"] == "documents"
    assert len(team.pdfs) == retained
    team.drain()
    # Two members compete for the same eight remaining questions.
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda who: ask(team, who), ["owner", "member"] * 5))
    assert sum(response.status_code == 200 for response in results) == 8
    assert sum(response.status_code == 429 for response in results) == 2
    for response in results:
        if response.status_code == 429:
            assert response.json()["detail"]["code"] == "quota_exceeded"
            assert response.json()["detail"]["metric"] == "chat_questions_month"
    used = request("owner", "GET", "/api/usage", workspace=workspace).json()
    assert used["chat"]["used"] == 10 and used["chat"]["remaining"] == 0
    assert used["documents"]["used"] == 5 and used["documents"]["remaining"] == 0
    assert used["costs"] == {"known_micros": 300, "unknown_calls": 0}
    assert sum(row["chat_questions"] for row in used["by_user"]) == 10


def test_team_archive_restore_and_member_removal_preserve_other_workspaces(team):
    request, workspace = team.request, team.workspace
    member_doc = team.docs["member"]
    response = ask(team, "member")
    assert response.status_code == 200
    conversation = response.headers["X-Conversation-Id"]
    member_path = f"/api/workspaces/{workspace}/members/{team.users['member']}"
    rejected = request("owner", "DELETE", member_path)
    assert rejected.status_code == 409
    assert rejected.json()["detail"]["document_count"] == 1
    assert request("member", "POST", f"/api/workspaces/{workspace}/archive").status_code == 404
    assert request("owner", "POST", f"/api/workspaces/{workspace}/archive").status_code == 200
    retained, indexed = dict(team.pdfs), dict(team.vectors)
    for who in ("owner", "member"):
        for path in ("/api/documents", "/api/usage", "/api/conversations", f"/api/conversations/{conversation}"):
            assert request(who, "GET", path, workspace=workspace).status_code == 404
        assert ask(team, who).status_code == 404
        assert request(who, "POST", "/api/upload", workspace=workspace,
                       files={"file": ("blocked.pdf", b"%PDF-1.4 blocked", "application/pdf")}).status_code == 404
        memberships = request(who, "GET", "/api/workspaces").json()["items"]
        assert {row["id"]: row["status"] for row in memberships}[workspace] == "archived"
    assert team.pdfs == retained and team.vectors == indexed
    assert request("owner", "POST", f"/api/workspaces/{workspace}/restore").status_code == 403
    assert request("admin", "POST", f"/api/workspaces/{workspace}/restore").status_code == 200
    restored = request("member", "GET", f"/api/conversations/{conversation}", workspace=workspace)
    assert restored.status_code == 200 and "member-private" in restored.json()["messages"][1]["content"]
    assert request("admin", "GET", f"/api/conversations/{conversation}", workspace=workspace).status_code == 404

    assert request("member", "DELETE", f"/api/documents/{member_doc}", workspace=workspace).status_code == 202
    assert request("member", "GET", f"/api/conversations/{conversation}", workspace=workspace).status_code == 404
    assert request("owner", "DELETE", member_path).status_code == 409  # Queued deletion still counts.
    team.drain()
    assert len(team.pdfs) == len(retained) - 1 and len(team.vectors) == len(indexed) - 1
    assert request("owner", "DELETE", member_path).status_code == 200
    for path in ("/api/documents", "/api/usage", "/api/conversations"):
        assert request("member", "GET", path, workspace=workspace).status_code == 404
    assert ask(team, "member").status_code == 404
    personal = request("member", "GET", f"/api/documents/{team.docs['personal']}/file", workspace=team.users["member"])
    assert personal.status_code == 200
    assert request("owner", "GET", f"/api/documents/{team.docs['owner']}", workspace=workspace).status_code == 200
    rejoined = request("owner", "POST", f"/api/workspaces/{workspace}/members", json={"user_id": team.users["member"]})
    assert rejoined.status_code == 201
    assert request("member", "GET", "/api/documents", workspace=workspace).json()["items"] == []
    assert request("member", "GET", f"/api/conversations/{conversation}", workspace=workspace).status_code == 404
