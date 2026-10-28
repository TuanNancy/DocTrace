"""Resumable workspace destruction using the existing document delete lifecycle.

Admission snapshots identifiers under the workspace lock. A durable SQL manifest
survives uncertain Redis/SQL outcomes, worker restarts and workspace removal.
No PDF/vector IO runs inside these transactions; only ordinary deletion jobs do it.
"""
import logging

from sqlalchemy import text

from app.core.config import AppConfig
from app.core.errors import api_error
from app.core.observability import bind_log_context, current_request_id, valid_request_id
from app.db import session_scope
from app.services.audit import write_audit
from app.services.document_repository import DocumentRepository, read_document
from app.services.transcripts import TranscriptService

logger = logging.getLogger(__name__)


def start_purge(session, actor: str, workspace_id: str, repository: DocumentRepository) -> dict:
    # All admissions lock workspace before member/document. FOR UPDATE waits for
    # already admitted mutations, then prevents new retries during the snapshot.
    state = session.execute(text("SELECT status FROM doctrace.workspaces WHERE id = :id FOR UPDATE"),
                            {"id": workspace_id}).scalar_one_or_none()
    if state == "purging":
        return purge_progress(session, workspace_id)
    if state != "archived":
        raise api_error(409 if state else 404, "workspace_not_archived" if state else "workspace_not_found",
                        "Workspace phải được archive trước khi xóa vĩnh viễn.")
    documents = repository.purge_snapshot_sync(workspace_id)
    request_id = current_request_id()
    session.execute(text("""
        INSERT INTO doctrace.workspace_purges (workspace_id, actor_user_id, request_id)
        VALUES (:id, :actor, :request)
        ON CONFLICT (workspace_id) DO UPDATE SET actor_user_id = EXCLUDED.actor_user_id,
            request_id = EXCLUDED.request_id, status = 'running', started_at = now(),
            updated_at = now(), completed_at = NULL
    """), {"id": workspace_id, "actor": actor, "request": request_id if valid_request_id(request_id) else None})
    # Personal workspaces may be provisioned again after an earlier purge.
    session.execute(text("DELETE FROM doctrace.workspace_purge_documents WHERE workspace_id = :id"), {"id": workspace_id})
    if documents:
        session.execute(text("""
            INSERT INTO doctrace.workspace_purge_documents (workspace_id, doc_id, owner_user_id)
            VALUES (:workspace, :doc_id, :owner_user_id)
        """), [{"workspace": workspace_id, **doc} for doc in documents])
    session.execute(text("UPDATE doctrace.workspaces SET status = 'purging', purge_started_at = now(), updated_at = now() WHERE id = :id"),
                    {"id": workspace_id})
    write_audit(session, actor, workspace_id, "workspace.purge_started", workspace_id, documents=len(documents))
    return purge_progress(session, workspace_id)


def purge_progress(session, workspace_id: str) -> dict:
    row = session.execute(text("""
        SELECT p.workspace_id::text, p.status, p.started_at, p.updated_at, p.completed_at,
            count(d.doc_id) AS total,
            count(d.doc_id) FILTER (WHERE d.status = 'deleted') AS deleted,
            count(d.doc_id) FILTER (WHERE d.status = 'failed') AS failed,
            count(d.doc_id) FILTER (WHERE d.status = 'deleting') AS deleting
        FROM doctrace.workspace_purges p
        LEFT JOIN doctrace.workspace_purge_documents d ON d.workspace_id = p.workspace_id
        WHERE p.workspace_id = :id GROUP BY p.workspace_id
    """), {"id": workspace_id}).mappings().first()
    if not row:
        raise api_error(404, "purge_not_found", "Không tìm thấy tiến trình xóa workspace.")
    return dict(row)


def _advance(session, config: AppConfig, workspace_id: str, repository: DocumentRepository) -> bool:
    state = session.execute(text("SELECT status FROM doctrace.workspaces WHERE id = :id FOR UPDATE SKIP LOCKED"),
                            {"id": workspace_id}).scalar_one_or_none()
    if state != "purging":
        return False
    purge = session.execute(text("SELECT * FROM doctrace.workspace_purges WHERE workspace_id = :id AND status = 'running' FOR UPDATE"),
                            {"id": workspace_id}).mappings().first()
    if not purge:
        return False
    with bind_log_context(request_id=purge["request_id"], workspace_id=workspace_id):
        remaining = session.execute(text("""
            SELECT doc_id::text, owner_user_id::text, status FROM doctrace.workspace_purge_documents
            WHERE workspace_id = :id AND status <> 'deleted' ORDER BY updated_at, doc_id LIMIT 50
        """), {"id": workspace_id}).mappings().all()
        if not remaining:
            # Only committed 'deleted' states reach this branch. If SQL fails
            # after Redis cleanup, replay accepts already missing tombstones.
            docs = session.execute(text("SELECT doc_id::text, owner_user_id::text FROM doctrace.workspace_purge_documents WHERE workspace_id = :id"),
                                   {"id": workspace_id}).mappings().all()
            repository.purge_cleanup_sync(workspace_id, docs)
            write_audit(session, str(purge["actor_user_id"]), workspace_id, "workspace.purge_completed", workspace_id)
            session.execute(text("DELETE FROM doctrace.workspaces WHERE id = :id"), {"id": workspace_id})
            session.execute(text("UPDATE doctrace.workspace_purges SET status = 'completed', completed_at = now(), updated_at = now() WHERE workspace_id = :id"),
                            {"id": workspace_id})
            return True
        transcripts = TranscriptService(config)
        for item in remaining:
            doc = repository._run_sync(read_document, item["doc_id"])
            if not doc or doc["workspace_id"] != workspace_id or doc["owner_user_id"] != item["owner_user_id"]:
                # Loss/corruption of authoritative catalog is not proof of cleanup.
                status = "failed"
            elif doc["status"] == "deleted":
                status = "deleted"
            else:
                # Reconcile first: a worker/container that died after accepting a
                # delete leaves a catalogued 'deleting' record whose RQ key is gone.
                # Without this read the manifest would wait forever.
                doc = repository.get_sync(workspace_id, item["owner_user_id"], item["doc_id"])
                if doc["status"] in ("ready", "error"):
                    doc = repository.queue_sync(workspace_id, item["owner_user_id"], item["doc_id"], "delete")
                status = "failed" if doc["status"] == "delete_error" else "deleting"
                if doc.get("delete_requested_at"):
                    transcripts._hide_for_document(session, workspace_id, item["owner_user_id"], item["doc_id"],
                                                   config.transcript_delete_mode, config.transcript_retention_days,
                                                   doc["delete_requested_at"])
            session.execute(text("UPDATE doctrace.workspace_purge_documents SET status = :status, updated_at = now() WHERE workspace_id = :wid AND doc_id = :did"),
                            {"status": status, "wid": workspace_id, "did": item["doc_id"]})
        session.execute(text("UPDATE doctrace.workspace_purges SET updated_at = now() WHERE workspace_id = :id"), {"id": workspace_id})
    return True


def advance_purges(config: AppConfig, *, limit: int = 10) -> int:
    if not config.database_url:
        return 0
    try:
        with session_scope(config) as session:
            ids = session.execute(text("SELECT workspace_id::text FROM doctrace.workspace_purges WHERE status = 'running' ORDER BY updated_at LIMIT :limit"),
                                  {"limit": limit}).scalars().all()
    except Exception:
        logger.warning("workspace_purge_failed", exc_info=True)
        return 0
    count = 0
    for workspace_id in ids:
        try:
            with session_scope(config) as session:
                count += int(_advance(session, config, workspace_id, DocumentRepository(config)))
        except Exception:
            logger.warning("workspace_purge_failed", extra={"workspace_id": workspace_id}, exc_info=True)
    return count
