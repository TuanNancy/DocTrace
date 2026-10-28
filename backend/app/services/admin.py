"""Platform administration: explicit metadata serializers and audited lifecycle.

No method queries messages, profiles, PDF storage or vector content. An admin
identity is checked in Postgres, never inferred from workspace ownership/JWT
user metadata. All blocking DB/Redis work stays off the event loop.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import logging
from uuid import uuid4

from fastapi import Depends, HTTPException
from redis import Redis
from rq import Queue, Worker
from rq.exceptions import NoSuchJobError
from rq.job import Job
from rq.serializers import JSONSerializer
from sqlalchemy import text
from starlette.concurrency import run_in_threadpool

from app.core.config import AppConfig, get_config
from app.core.errors import api_error
from app.db import session_scope
from app.services.audit import ACTIONS, write_audit
from app.services.document_locks import lock_document
from app.services.document_repository import DocumentRepository, admin_document, get_document_repository, global_key, read_document
from app.services.failures import ERROR_MESSAGES, flush_failures_async
from app.services.readiness import readiness
from app.services.transcripts import TranscriptService
from app.services.purges import start_purge, purge_progress

logger = logging.getLogger(__name__)


def require_admin(session, user_id: str) -> None:
    if not session.execute(text("SELECT 1 FROM doctrace.platform_admins WHERE user_id = CAST(:id AS uuid)"),
                           {"id": user_id}).scalar():
        raise api_error(403, "admin_required", "Chỉ platform admin được sử dụng chức năng này.")


def _rows(result):
    return [dict(row) for row in result.mappings()]


class AdminService:
    def __init__(self, config: AppConfig, repository: DocumentRepository):
        self.config, self.repository = config, repository

    async def _run(self, actor: str, action, *args):
        def run():
            with session_scope(self.config) as session:
                require_admin(session, actor)
                return action(session, *args)
        try:
            return await run_in_threadpool(run)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("admin_operation_failed")
            raise api_error(503, "admin_unavailable", "Không thể truy cập dịch vụ quản trị.") from exc

    async def assert_admin(self, actor: str) -> None:
        await self._run(actor, lambda session: None)

    async def overview(self, actor: str, days: int = 30) -> dict:
        def report(session):
            since = datetime.now(timezone.utc) - timedelta(days=days)
            scope = {"since": since}
            statuses = _rows(session.execute(text("SELECT status, count(*) AS count FROM doctrace.workspaces GROUP BY status")))
            costs = _rows(session.execute(text("""
                SELECT cost_status, count(*) AS calls, COALESCE(sum(cost_micros), 0)::bigint AS known_micros
                FROM doctrace.provider_calls WHERE created_at >= :since GROUP BY cost_status
                ORDER BY cost_status
            """), scope))
            chat = dict(session.execute(text("""
                SELECT count(*) AS requests, count(*) FILTER (WHERE status = 'failed') AS failed,
                    count(*) FILTER (WHERE status = 'interrupted') AS interrupted,
                    count(*) FILTER (WHERE cache_hit) AS cache_hits,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms) AS latency_p50_ms,
                    percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms) AS latency_p95_ms,
                    percentile_cont(0.5) WITHIN GROUP (ORDER BY first_token_ms) AS first_token_p50_ms,
                    percentile_cont(0.95) WITHIN GROUP (ORDER BY first_token_ms) AS first_token_p95_ms
                FROM doctrace.chat_requests WHERE created_at >= :since
            """), scope).mappings().one())
            breakdown = {}
            for dimension, expression in (
                ("day", "to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD')"),
                ("model", "model"), ("workspace", "workspace_id::text"), ("kind", "kind"),
            ):
                breakdown[dimension] = _rows(session.execute(text(f"""
                    SELECT {expression} AS key, count(*) AS calls,
                        COALESCE(sum(cost_micros), 0)::bigint AS known_micros,
                        count(*) FILTER (WHERE cost_micros IS NULL) AS unknown_calls
                    FROM doctrace.provider_calls WHERE created_at >= :since
                    GROUP BY 1 ORDER BY known_micros DESC, key LIMIT 100
                """), scope))
            documents = self.repository._run_sync(lambda redis: int(redis.zcard(global_key())))
            return {"since": since.isoformat(), "workspaces": statuses, "documents": documents,
                    "costs": costs, "by": breakdown, "chat": chat}
        return await self._run(actor, report)

    async def workspaces(self, actor: str, limit: int, offset: int) -> dict:
        def listing(session):
            rows = _rows(session.execute(text("""
                SELECT w.id::text, w.name, w.kind, w.plan, w.status, w.created_by::text, w.created_at,
                    (SELECT count(*) FROM doctrace.workspace_members m
                     WHERE m.workspace_id = w.id AND m.status = 'active') AS members
                FROM doctrace.workspaces w ORDER BY w.created_at DESC, w.id LIMIT :limit OFFSET :offset
            """), {"limit": limit + 1, "offset": offset}))
            for row in rows[:limit]:
                row["documents"] = self.repository.count_workspace_sync(row["id"])
            return {"items": rows[:limit], "next_offset": offset + limit if len(rows) > limit else None}
        return await self._run(actor, listing)

    async def change_plan(self, actor: str, workspace_id: str, plan: str) -> dict:
        if plan not in ("free", "pro"):
            raise api_error(400, "plan_invalid", "Gói không hợp lệ.")
        def change(session):
            previous = session.execute(text("""
                SELECT plan FROM doctrace.workspaces WHERE id = CAST(:id AS uuid)
                    AND status <> 'purging' FOR UPDATE
            """), {"id": workspace_id}).scalar_one_or_none()
            if previous is None:
                raise api_error(404, "workspace_not_found", "Không tìm thấy workspace.")
            if previous != plan:
                session.execute(text("UPDATE doctrace.workspaces SET plan = :plan, updated_at = now() WHERE id = CAST(:id AS uuid)"),
                                {"id": workspace_id, "plan": plan})
                write_audit(session, actor, workspace_id, "workspace.plan_changed", workspace_id,
                            from_plan=previous, to_plan=plan)
            return {"id": workspace_id, "plan": plan}
        return await self._run(actor, change)

    async def start_purge(self, actor: str, workspace_id: str) -> dict:
        return await self._run(actor, lambda session: start_purge(session, actor, workspace_id, self.repository))

    async def archive(self, actor: str, workspace_id: str) -> dict:
        def change(session):
            row = session.execute(text("""
                UPDATE doctrace.workspaces SET status = 'archived', archived_at = now(),
                    archived_by = :actor, updated_at = now() WHERE id = :id AND status = 'active'
                RETURNING id::text, status
            """), {"actor": actor, "id": workspace_id}).mappings().first()
            if not row:
                raise api_error(409, "workspace_not_active", "Workspace không còn hoạt động.")
            write_audit(session, actor, workspace_id, "workspace.archived", workspace_id)
            return dict(row)
        return await self._run(actor, change)

    async def restore(self, actor: str, workspace_id: str) -> dict:
        from app.services.workspaces import WorkspaceService
        return await self._run(actor, lambda session: WorkspaceService(self.config)._restore(session, actor, workspace_id))

    async def purges(self, actor: str, limit: int, offset: int) -> dict:
        def listing(session):
            ids = session.execute(text("SELECT workspace_id::text FROM doctrace.workspace_purges ORDER BY started_at DESC, workspace_id LIMIT :limit OFFSET :offset"),
                                  {"limit": limit + 1, "offset": offset}).scalars().all()
            return {"items": [purge_progress(session, wid) for wid in ids[:limit]],
                    "next_offset": offset + limit if len(ids) > limit else None}
        return await self._run(actor, listing)

    async def documents(self, actor: str, workspace_id: str | None, status: str | None,
                        limit: int, offset: int) -> dict:
        await self.assert_admin(actor)
        return await self.repository.admin_catalog(workspace_id, status=status, limit=limit, offset=offset)

    async def failures(self, actor: str, workspace_id: str | None, limit: int, offset: int) -> dict:
        await self.assert_admin(actor)
        await flush_failures_async(self.config)
        def listing(session):
            rows = _rows(session.execute(text("""
                SELECT id::text, workspace_id::text, owner_user_id::text, doc_id::text,
                    job_id, attempt, kind, error_code, request_id, created_at
                FROM doctrace.document_failures
                WHERE (CAST(:workspace AS uuid) IS NULL OR workspace_id = CAST(:workspace AS uuid))
                ORDER BY created_at DESC, id LIMIT :limit OFFSET :offset
            """), {"workspace": workspace_id, "limit": limit + 1, "offset": offset}))
            for row in rows[:limit]:
                row["message"] = ERROR_MESSAGES[row["error_code"]]
            return {"items": rows[:limit], "next_offset": offset + limit if len(rows) > limit else None}
        return await self._run(actor, listing)

    async def audit(self, actor: str, limit: int, offset: int) -> dict:
        def listing(session):
            rows = _rows(session.execute(text("""
                SELECT id::text, actor_user_id::text, workspace_id::text, action, target_type,
                    target_id, metadata, request_id, created_at
                FROM doctrace.audit_events ORDER BY created_at DESC, id LIMIT :limit OFFSET :offset
            """), {"limit": limit + 1, "offset": offset}))
            for row in rows:
                _, fields = ACTIONS.get(row["action"], ("unknown", set()))
                row["metadata"] = {key: value for key, value in row["metadata"].items() if key in fields}
            return {"items": rows[:limit], "next_offset": offset + limit if len(rows) > limit else None}
        return await self._run(actor, listing)

    def _retry_target(self, session, doc_id: str) -> dict:
        doc = self.repository._run_sync(read_document, doc_id)
        if not doc or doc["status"] == "deleted":
            raise api_error(404, "document_not_found", "Không tìm thấy tài liệu.")
        state = session.execute(text("""
            SELECT status FROM doctrace.workspaces WHERE id = CAST(:id AS uuid) FOR SHARE
        """), {"id": doc["workspace_id"]}).scalar_one_or_none()
        if state is None:
            raise api_error(404, "workspace_not_found", "Không tìm thấy workspace.")
        doc = self.repository.get_sync(doc["workspace_id"], doc["owner_user_id"], doc_id)
        if doc["status"] not in ("error", "delete_error"):
            raise api_error(409, "document_not_retryable", "Chỉ có thể thử lại tài liệu bị lỗi.")
        if state == "purging" and doc["status"] != "delete_error":
            raise api_error(409, "workspace_purging", "Workspace đang được xóa.")
        return doc

    async def retry(self, actor: str, doc_id: str) -> dict:
        def intent(session):
            doc = self._retry_target(session, doc_id)
            kind = "delete" if doc["status"] == "delete_error" else "index"
            write_audit(session, actor, doc["workspace_id"], "document.retry_requested", doc_id, kind=kind)
            return doc["workspace_id"], doc["owner_user_id"], kind
        # Commit intent before touching Redis: even an uncertain SQL/Redis
        # outcome leaves a durable actor/request/target audit, never a false
        # 'accepted' event. A second request rechecks lifecycle, not RQ requeue.
        workspace, owner, kind = await self._run(actor, intent)
        def enqueue(session):
            doc = self._retry_target(session, doc_id)
            if (doc["workspace_id"], doc["owner_user_id"], doc["status"] == "delete_error") != (workspace, owner, kind == "delete"):
                raise api_error(409, "document_changed", "Trạng thái tài liệu đã thay đổi.")
            lock_document(session, workspace, owner, doc_id)
            doc = self.repository.queue_sync(workspace, owner, doc_id, kind)
            if kind == "delete":
                TranscriptService(self.config)._hide_for_document(
                    session, workspace, owner, doc_id, self.config.transcript_delete_mode,
                    self.config.transcript_retention_days, doc.get("delete_requested_at"),
                )
            write_audit(session, actor, workspace, "document.retry_accepted", doc_id,
                        kind=kind, job_id=doc["job_id"])
            return admin_document(doc)
        return await self._run(actor, enqueue)

    async def health(self, actor: str) -> dict:
        await self.assert_admin(actor)
        base, queues, vector = await asyncio.gather(
            readiness(self.config), run_in_threadpool(_queue_health, self.config),
            run_in_threadpool(_vector_health, self.config),
        )
        checks = {**base[1], "queue": queues, "milvus": vector}
        return {"status": "ok" if all(item["status"] == "ok" for item in checks.values()) else "degraded",
                "checks": checks}


def _queue_health(config: AppConfig) -> dict:
    try:
        with Redis.from_url(config.redis_url, socket_connect_timeout=2, socket_timeout=2) as connection:
            queue = Queue(config.rq_queue_name, connection=connection, serializer=JSONSerializer)
            now = datetime.now(timezone.utc)
            workers = [worker for worker in Worker.all(queue=queue, connection=connection)
                       if worker.last_heartbeat and (now - worker.last_heartbeat).total_seconds() <= worker.worker_ttl]
            oldest = None
            for job_id in queue.get_job_ids(offset=0, length=1):
                try:
                    job = Job.fetch(job_id, connection=connection, serializer=JSONSerializer)
                    if job.enqueued_at:
                        oldest = max(0, int((now - job.enqueued_at).total_seconds()))
                except NoSuchJobError:
                    pass
            return {"status": "ok" if workers else "degraded", "workers": len(workers),
                    "queued": queue.count, "started": queue.started_job_registry.count,
                    "scheduled": queue.scheduled_job_registry.count, "failed": queue.failed_job_registry.count,
                    "oldest_queued_seconds": oldest}
    except Exception:
        logger.warning("admin_health_failed", exc_info=True)
        return {"status": "error", "error_code": "queue_unavailable"}


def _vector_health(config: AppConfig) -> dict:
    from pymilvus import connections, has_collection
    alias = f"doctrace_probe_{uuid4().hex}"
    kwargs = ({"uri": config.milvus_uri, "token": config.milvus_token or "",
               "secure": config.milvus_uri.startswith("https://")} if config.milvus_uri
              else {"host": config.milvus_host, "port": config.milvus_port})
    try:
        connections.connect(alias=alias, timeout=2, **kwargs)
        exists = has_collection(config.milvus_collection, using=alias, timeout=2)
        return {"status": "ok" if exists else "degraded", "collection_exists": exists}
    except Exception:
        logger.warning("admin_health_failed", exc_info=True)
        return {"status": "error", "error_code": "milvus_unavailable"}
    finally:
        connections.remove_connection(alias)


def get_admin_service(repository: DocumentRepository = Depends(get_document_repository)) -> AdminService:
    return AdminService(get_config(), repository)
