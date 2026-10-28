"""Administrative HTTP boundaries and resumable cross-store operations.

Uses the hosted-shaped runtime/real Redis team acceptance fixtures. Only PDF,
vector, Auth HTTP and provider boundaries are replaced.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from threading import Event
from unittest.mock import Mock
from uuid import uuid4

from fastapi import HTTPException
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from rq.job import Job, JobStatus
from rq.serializers import JSONSerializer
from sqlalchemy import text

from app.jobs import documents as jobs
from app.services import admin as admin_module, failures, purges
from app.services.admin import AdminService, _queue_health
from app.services.document_repository import (
    ADMIN_FIELDS, DocumentRepository, document_key, global_key, legacy_user_key,
    read_document, workspace_key, workspace_user_key,
)
from app.services.pdf_indexing import InvalidPDFError
from app.services.quotas import QuotaService
from app.services.transcripts import TranscriptService
from app.services.workspaces import WorkspaceService
from tests.test_team_acceptance import _docker_available, ask, infrastructure, team  # noqa: F401
from tests.test_workspace_service_pg import wait_for_lock

pytestmark = pytest.mark.skipif(not _docker_available(), reason="Admin acceptance requires Docker")


def scalar(team, query, **params):
    with team.admin.connect() as connection:
        return connection.execute(text(query), params).scalar()


@pytest.mark.parametrize("who", ["owner", "member"])
def test_workspace_roles_cannot_query_admin_before_catalog_access(team, monkeypatch, who):
    catalog = Mock(side_effect=AssertionError("must authorize before Redis"))
    monkeypatch.setattr(DocumentRepository, "_run_sync", catalog)
    for path in ("overview", "workspaces", "documents", "failures", "audit", "health", "purges"):
        response = team.request(who, "GET", f"/api/admin/{path}")
        assert response.status_code == 403, response.text
    assert team.request(who, "PATCH", f"/api/admin/workspaces/{team.workspace}/plan", json={"plan": "pro"}).status_code == 403
    assert team.request(who, "POST", f"/api/admin/documents/{team.docs['member']}/retry").status_code == 403
    assert team.request(who, "POST", f"/api/admin/workspaces/{team.workspace}/purge", json={"confirm_workspace_id": team.workspace}).status_code == 403
    catalog.assert_not_called()


def test_admin_metadata_cost_timing_and_plan_changes_preserve_usage(team, monkeypatch):
    assert ask(team, "member").status_code == 200
    for plan in ("pro", "free"):
        changed = team.request("admin", "PATCH", f"/api/admin/workspaces/{team.workspace}/plan", json={"plan": plan})
        assert changed.status_code == 200
        usage = team.request("owner", "GET", "/api/usage", workspace=team.workspace).json()
        assert usage["plan"] == plan and usage["chat"]["used"] == 1
    result = team.request("admin", "GET", "/api/admin/documents", params={"workspace_id": team.workspace})
    assert result.status_code == 200
    assert {doc["doc_id"] for doc in result.json()["items"]} == {team.docs["member"], team.docs["owner"]}
    assert all(set(doc) == set(ADMIN_FIELDS) for doc in result.json()["items"])
    report = team.request("admin", "GET", "/api/admin/overview").json()
    assert report["chat"]["requests"] >= 1
    assert report["chat"]["latency_p50_ms"] is not None
    assert report["chat"]["first_token_p50_ms"] is not None
    row = next(row for row in report["by"]["workspace"] if row["key"] == team.workspace)
    assert row["known_micros"] == 45 and row["unknown_calls"] == 0
    assert {row["key"] for row in report["by"]["kind"]} >= {"index_embedding", "answer"}
    audit = team.request("admin", "GET", "/api/admin/audit").json()
    for value in (result.json(), report, audit):
        serialized = json.dumps(value)
        assert "private.pdf" not in serialized and "Question from" not in serialized and "token=" not in serialized
    # The SQL update and its audit either both commit or both roll back.
    monkeypatch.setattr(admin_module, "write_audit", Mock(side_effect=RuntimeError("audit unavailable")))
    assert team.request("admin", "PATCH", f"/api/admin/workspaces/{team.workspace}/plan", json={"plan": "pro"}).status_code == 503
    assert scalar(team, "SELECT plan FROM doctrace.workspaces WHERE id = :id", id=team.workspace) == "free"


def test_terminal_invalid_pdf_persists_beyond_rq_and_retry_is_audited(team, monkeypatch):
    original = jobs.index_pdf_bytes
    async def invalid(*args, **kwargs):
        raise InvalidPDFError("PRIVATE PDF TEXT https://signed.example?secret=abc")
    monkeypatch.setattr(jobs, "index_pdf_bytes", invalid)
    doc_id = team.upload("member", team.workspace, "secret-name")
    team.drain()  # A permanent invalid PDF finishes in RQ, but fails in the catalog.
    doc = read_document(team.redis, doc_id)
    assert doc["status"] == "error"
    assert Job.fetch(doc["job_id"], connection=team.redis, serializer=JSONSerializer).get_status() == JobStatus.FINISHED
    team.redis.delete(Job.key_for(doc["job_id"]))
    result = team.request("admin", "GET", "/api/admin/failures", params={"workspace_id": team.workspace})
    assert result.status_code == 200
    row = next(row for row in result.json()["items"] if row["doc_id"] == doc_id)
    assert row["error_code"] == "invalid_pdf" and row["owner_user_id"] == team.users["member"]
    assert "PRIVATE" not in result.text and "secret-name" not in result.text
    monkeypatch.setattr(jobs, "index_pdf_bytes", original)
    retried = team.request("admin", "POST", f"/api/admin/documents/{doc_id}/retry")
    assert retried.status_code == 202 and set(retried.json()) == set(ADMIN_FIELDS)
    assert team.request("admin", "POST", f"/api/admin/documents/{doc_id}/retry").status_code == 409
    team.drain()
    current = read_document(team.redis, doc_id)
    assert current["status"] == "ready" and current["job_id"] != doc["job_id"]
    assert scalar(team, "SELECT count(*) FROM doctrace.audit_events WHERE target_id = :id AND action LIKE 'document.retry_%'", id=doc_id) == 2
    assert scalar(team, "SELECT workspace_id::text FROM doctrace.provider_calls WHERE job_id = :id", id=current["job_id"]) == team.workspace


def test_failure_outbox_survives_sql_and_acknowledgment_failures(team, monkeypatch):
    doc = read_document(team.redis, team.docs["member"])
    event_id = None
    with team.redis.pipeline() as pipeline:
        failures.stage_failure(pipeline, doc, "index_failed")
        pipeline.execute()
    for raw_id, raw in team.redis.hgetall(failures.OUTBOX_KEY).items():
        if json.loads(raw)["doc_id"] == doc["doc_id"]:
            event_id = raw_id
    assert event_id
    original_scope = failures.session_scope
    @contextmanager
    def unavailable(config):
        raise RuntimeError("database outage")
        yield  # pragma: no cover
    monkeypatch.setattr(failures, "session_scope", unavailable)
    assert failures.flush_failures(team.config) == 0
    assert team.redis.hexists(failures.OUTBOX_KEY, event_id)
    monkeypatch.setattr(failures, "session_scope", original_scope)
    original_hdel = failures.Redis.hdel
    monkeypatch.setattr(failures.Redis, "hdel", Mock(side_effect=RedisConnectionError("lost acknowledgment")))
    assert failures.flush_failures(team.config) == 0
    assert team.redis.hexists(failures.OUTBOX_KEY, event_id)
    monkeypatch.setattr(failures.Redis, "hdel", original_hdel)
    assert failures.flush_failures(team.config) >= 1
    assert not team.redis.hexists(failures.OUTBOX_KEY, event_id)
    assert scalar(team, "SELECT count(*) FROM doctrace.document_failures WHERE id = :id", id=event_id.decode()) == 1


def test_purge_requires_archive_no_live_jobs_confirmation_and_admin(team):
    path = f"/api/admin/workspaces/{team.workspace}/purge"
    confirm = {"confirm_workspace_id": team.workspace}
    assert team.request("admin", "POST", path, json=confirm).json()["detail"]["code"] == "workspace_not_archived"
    doc_id = team.upload("member", team.workspace, "inflight")
    assert team.request("owner", "POST", f"/api/workspaces/{team.workspace}/archive").status_code == 200
    assert team.request("admin", "POST", path, json={"confirm_workspace_id": str(uuid4())}).status_code == 400
    blocked = team.request("admin", "POST", path, json=confirm)
    assert blocked.status_code == 409 and blocked.json()["detail"]["code"] == "workspace_jobs_live"
    team.drain()
    assert read_document(team.redis, doc_id)["status"] == "ready"


def test_purge_resumes_after_sql_failure_preserves_other_workspaces_and_costs(team, monkeypatch):
    assert ask(team, "member").status_code == 200
    assert team.request("owner", "POST", f"/api/workspaces/{team.workspace}/archive").status_code == 200
    start = team.request("admin", "POST", f"/api/admin/workspaces/{team.workspace}/purge",
                         json={"confirm_workspace_id": team.workspace})
    assert start.status_code == 202 and start.json()["total"] == 2
    assert team.request("admin", "POST", f"/api/workspaces/{team.workspace}/restore").status_code == 404
    original = TranscriptService._hide_for_document
    monkeypatch.setattr(TranscriptService, "_hide_for_document", Mock(side_effect=RuntimeError("SQL outage after Redis admission")))
    purges.advance_purges(team.config)
    assert any(read_document(team.redis, team.docs[who])["status"] == "deleting" for who in ("owner", "member"))
    # Progress rolls back, while the accepted Redis job remains recoverable.
    assert scalar(team, "SELECT count(*) FROM doctrace.workspace_purge_documents WHERE workspace_id = :id AND status = 'pending'", id=team.workspace) == 2
    monkeypatch.setattr(TranscriptService, "_hide_for_document", original)
    purges.advance_purges(team.config)
    assert scalar(team, "SELECT status FROM doctrace.workspaces WHERE id = :id", id=team.workspace) == "purging"
    team.drain()
    purges.advance_purges(team.config)  # Persist proof of external cleanup.
    assert scalar(team, "SELECT count(*) FROM doctrace.workspace_purge_documents WHERE workspace_id = :id AND status = 'deleted'", id=team.workspace) == 2
    audit = purges.write_audit
    monkeypatch.setattr(purges, "write_audit", Mock(side_effect=RuntimeError("SQL outage after catalog cleanup")))
    purges.advance_purges(team.config)
    assert not team.redis.exists(document_key(team.docs["member"]))
    assert scalar(team, "SELECT status FROM doctrace.workspaces WHERE id = :id", id=team.workspace) == "purging"
    monkeypatch.setattr(purges, "write_audit", audit)
    purges.advance_purges(team.config)  # Remove catalog and SQL metadata.
    assert scalar(team, "SELECT count(*) FROM doctrace.workspaces WHERE id = :id", id=team.workspace) == 0
    assert scalar(team, "SELECT count(*) FROM doctrace.conversations WHERE workspace_id = :id", id=team.workspace) == 0
    assert scalar(team, "SELECT count(*) FROM doctrace.provider_calls WHERE doc_id = :id AND workspace_id IS NULL", id=team.docs["member"]) == 2
    assert scalar(team, "SELECT count(*) FROM doctrace.audit_events WHERE workspace_id = :id AND action = 'workspace.purge_completed'", id=team.workspace) == 1
    assert not team.redis.exists(document_key(team.docs["member"]))
    assert len(team.pdfs) == len(team.vectors) == 1
    assert team.request("member", "GET", f"/api/documents/{team.docs['personal']}/file", workspace=team.users["member"]).status_code == 200
    progress = team.request("admin", "GET", "/api/admin/purges").json()
    item = next(row for row in progress["items"] if row["workspace_id"] == team.workspace)
    assert item["status"] == "completed" and item["deleted"] == item["total"] == 2
    purges.advance_purges(team.config)


def test_stale_admissions_fail_after_archive(team):
    repository = DocumentRepository(team.config)
    workspaces, transcripts = WorkspaceService(team.config), TranscriptService(team.config)
    assert team.request("owner", "POST", f"/api/workspaces/{team.workspace}/archive").status_code == 200
    calls = [
        workspaces.retry_document(team.workspace, team.users["member"], team.docs["member"], repository),
        transcripts.queue_document_deletion(team.workspace, team.users["member"], team.docs["member"], repository),
        QuotaService(team.config, repository).admit_chat(team.workspace, team.users["member"], str(uuid4()), team.docs["member"], "pro"),
    ]
    for call in calls:
        with pytest.raises(HTTPException) as error:
            asyncio.run(call)
        assert error.value.status_code == 404


def test_queue_health_reports_oldest_job_only_and_worker_absence(team):
    team.upload("owner", team.workspace, "queued-first")
    health = _queue_health(team.config)
    assert health["status"] == "degraded" and health["workers"] == 0
    assert health["queued"] == 1 and health["oldest_queued_seconds"] is not None
    team.drain()


def start(team, workspace=None):
    workspace = workspace or team.workspace
    assert team.request("admin", "POST", f"/api/admin/workspaces/{workspace}/archive").status_code == 200
    response = team.request("admin", "POST", f"/api/admin/workspaces/{workspace}/purge",
                            json={"confirm_workspace_id": workspace})
    assert response.status_code == 202, response.text
    return response.json()


def test_purge_delete_failure_waits_for_audited_retry_and_preserves_retention_clock(team, monkeypatch):
    start(team)
    purges.advance_purges(team.config)
    doc = read_document(team.redis, team.docs["member"])
    job = Job.fetch(doc["job_id"], connection=team.redis, serializer=JSONSerializer)
    job.retries_left = 0
    job.save()
    original = jobs.delete_pdf
    def unavailable(key):
        if key == doc["storage_key"]:
            raise RuntimeError("private storage failure")
        return original(key)
    monkeypatch.setattr(jobs, "delete_pdf", unavailable)
    team.drain(expected_failures=1)
    for _ in range(2):
        purges.advance_purges(team.config)
    failed = read_document(team.redis, doc["doc_id"])
    assert failed["status"] == "delete_error" and failed["job_id"] == job.id
    assert scalar(team, "SELECT status FROM doctrace.workspace_purge_documents WHERE doc_id = :id", id=doc["doc_id"]) == "failed"
    assert scalar(team, "SELECT error_code FROM doctrace.document_failures WHERE job_id = :id", id=job.id) == "delete_failed"
    monkeypatch.setattr(jobs, "delete_pdf", original)
    response = team.request("admin", "POST", f"/api/admin/documents/{doc['doc_id']}/retry")
    assert response.status_code == 202, response.text
    retried = read_document(team.redis, doc["doc_id"])
    assert retried["job_id"] != job.id and retried["delete_requested_at"] == doc["delete_requested_at"]
    team.drain(expected_failures=1)
    purges.advance_purges(team.config)
    purges.advance_purges(team.config)
    assert scalar(team, "SELECT status FROM doctrace.workspace_purges WHERE workspace_id = :id", id=team.workspace) == "completed"
    assert scalar(team, "SELECT count(*) FROM doctrace.audit_events WHERE target_id = :id AND action LIKE 'document.retry_%'", id=doc["doc_id"]) == 2
    # Keep this module's shared queue clean for subsequent acceptance cases.
    job.delete()


def test_purge_reconciles_lost_delete_jobs_instead_of_waiting_forever(team):
    start(team)
    purges.advance_purges(team.config)
    for who in ("owner", "member"):
        doc = read_document(team.redis, team.docs[who])
        assert doc["status"] == "deleting"
        # Simulate a worker/container dying after the enqueue committed.
        team.redis.delete(Job.key_for(doc["job_id"]))
    purges.advance_purges(team.config)
    for who in ("owner", "member"):
        failed = read_document(team.redis, team.docs[who])
        assert failed["status"] == "delete_error" and failed["error_code"] == "job_interrupted"
    assert scalar(team, "SELECT count(*) FROM doctrace.workspace_purge_documents WHERE workspace_id = :id AND status = 'failed'", id=team.workspace) == 2
    failures.flush_failures(team.config)
    assert scalar(team, "SELECT count(*) FROM doctrace.document_failures WHERE workspace_id = :id AND error_code = 'job_interrupted'", id=team.workspace) == 2
    assert scalar(team, "SELECT status FROM doctrace.workspaces WHERE id = :id", id=team.workspace) == "purging"


def test_purge_replay_after_lost_sql_commit_and_personal_reprovisioning(team, monkeypatch):
    workspace = team.users["member"]
    start(team, workspace)
    purges.advance_purges(team.config)
    team.drain()
    purges.advance_purges(team.config)
    original = purges.session_scope
    @contextmanager
    def lost_commit(config):
        with original(config) as session:
            yield session
        raise ConnectionError("commit reply lost")
    monkeypatch.setattr(purges, "session_scope", lost_commit)
    # Simulate only the finalization transaction, not the manifest-list read.
    with pytest.raises(ConnectionError):
        with lost_commit(team.config) as session:
            assert purges._advance(session, team.config, workspace, DocumentRepository(team.config))
    monkeypatch.setattr(purges, "session_scope", original)
    purges.advance_purges(team.config)
    assert scalar(team, "SELECT count(*) FROM doctrace.audit_events WHERE workspace_id = :id AND action = 'workspace.purge_completed'", id=workspace) == 1
    assert team.request("member", "GET", "/api/workspaces").status_code == 200
    assert start(team, workspace)["total"] == 0  # Old manifest is replaced.
    purges.advance_purges(team.config)
    assert scalar(team, "SELECT status FROM doctrace.workspace_purges WHERE workspace_id = :id", id=workspace) == "completed"
    assert scalar(team, "SELECT count(*) FROM doctrace.audit_events WHERE workspace_id = :id AND action = 'workspace.purge_completed'", id=workspace) == 2


@pytest.mark.parametrize("legacy", [False, True])
def test_purge_includes_previously_deleted_unindexed_tombstones(team, legacy):
    workspace = team.users["member"] if legacy else team.workspace
    doc_id = team.docs["personal"] if legacy else team.docs["member"]
    response = team.request("member", "DELETE", f"/api/documents/{doc_id}", workspace=workspace)
    assert response.status_code == 202
    team.drain()
    tombstone = read_document(team.redis, doc_id)
    assert tombstone["status"] == "deleted"
    assert tombstone["name"] and tombstone["storage_key"]
    for key in (workspace_key(workspace), global_key(), legacy_user_key(team.users["member"]),
                workspace_user_key(workspace, team.users["member"])):
        assert team.redis.zscore(key, doc_id) is None
    if legacy:
        del tombstone["workspace_id"], tombstone["owner_user_id"]
        team.redis.hset(document_key(doc_id), "data", json.dumps(tombstone))
    expected = 1 if legacy else 2
    assert start(team, workspace)["total"] == expected
    purges.advance_purges(team.config)
    team.drain()
    purges.advance_purges(team.config)
    purges.advance_purges(team.config)
    assert scalar(team, "SELECT status FROM doctrace.workspace_purges WHERE workspace_id = :id", id=workspace) == "completed"
    assert not team.redis.exists(document_key(doc_id))
    other = team.docs["member"] if legacy else team.docs["personal"]
    assert read_document(team.redis, other)["status"] == "ready"


def test_purge_missing_catalog_is_not_proof_of_external_cleanup(team):
    start(team)
    team.redis.delete(document_key(team.docs["member"]))
    purges.advance_purges(team.config)
    assert scalar(team, "SELECT status FROM doctrace.workspace_purge_documents WHERE doc_id = :id", id=team.docs["member"]) == "failed"
    assert scalar(team, "SELECT status FROM doctrace.workspaces WHERE id = :id", id=team.workspace) == "purging"
    team.drain()
    # This corruption scenario remains blocked; isolate its recovery record.
    with team.admin.begin() as connection:
        connection.execute(text("DELETE FROM doctrace.workspace_purges WHERE workspace_id = :id"), {"id": team.workspace})


def test_purge_waits_for_retry_admission_then_rejects_live_job(team, monkeypatch):
    async def invalid(*args, **kwargs):
        raise InvalidPDFError("fixture")
    monkeypatch.setattr(jobs, "index_pdf_bytes", invalid)
    doc_id = team.upload("member", team.workspace, "invalid")
    team.drain()
    assert team.request("admin", "POST", f"/api/admin/workspaces/{team.workspace}/archive").status_code == 200
    entered, release = Event(), Event()
    original = DocumentRepository.queue_sync
    def blocked(self, *args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(self, *args, **kwargs)
    monkeypatch.setattr(DocumentRepository, "queue_sync", blocked)
    service = AdminService(team.config, DocumentRepository(team.config))
    with ThreadPoolExecutor(max_workers=2) as pool:
        retry = pool.submit(asyncio.run, service.retry(team.users["admin"], doc_id))
        assert entered.wait(5)
        purge = pool.submit(asyncio.run, service.start_purge(team.users["admin"], team.workspace))
        try:
            asyncio.run(wait_for_lock(team.admin.url))
        finally:
            release.set()
        retried = retry.result(timeout=10)
        with pytest.raises(HTTPException) as error:
            purge.result(timeout=10)
        rejected = error.value
    assert retried["status"] == "queued"
    assert isinstance(rejected, HTTPException) and rejected.detail["code"] == "workspace_jobs_live"
    assert scalar(team, "SELECT status FROM doctrace.workspaces WHERE id = :id", id=team.workspace) == "archived"
    team.drain()


def test_plan_downgrade_during_upload_rechecks_limit_and_cleans_retained_pdf(team, monkeypatch):
    assert team.request("admin", "PATCH", f"/api/admin/workspaces/{team.workspace}/plan", json={"plan": "pro"}).status_code == 200
    for number in range(3):
        team.upload("member", team.workspace, f"extra-{number}")
    from app.routers import upload
    store = upload.upload_pdf_to_supabase_storage
    def downgrade(data, key):
        store(data, key)
        assert team.request("admin", "PATCH", f"/api/admin/workspaces/{team.workspace}/plan", json={"plan": "free"}).status_code == 200
    monkeypatch.setattr(upload, "upload_pdf_to_supabase_storage", downgrade)
    retained = len(team.pdfs)
    response = team.request("member", "POST", "/api/upload", workspace=team.workspace,
                            files={"file": ("late.pdf", b"%PDF-1.4 fixture", "application/pdf")})
    assert response.status_code == 429 and response.json()["detail"]["limit"] == 5
    assert len(team.pdfs) == retained
    team.drain()
    quotas = QuotaService(team.config, DocumentRepository(team.config))
    for _ in range(10):
        asyncio.run(quotas.admit_chat(team.workspace, team.users["member"], str(uuid4()), team.docs["member"], "pro"))
    with pytest.raises(HTTPException) as error:
        asyncio.run(quotas.admit_chat(team.workspace, team.users["member"], str(uuid4()), team.docs["member"], "pro"))
    assert error.value.status_code == 429 and error.value.detail["limit"] == 10
