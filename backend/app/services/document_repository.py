"""Workspace-scoped Redis library. Catalog records have no TTL; RQ jobs do.

Documents stay private to their owner: a record must match both the selected
workspace and the authenticated user. Every write uses WATCH to serialize
changes to one document. Enqueue and the catalog indexes share MULTI/EXEC on
the same Redis instance. Synchronous Redis/RQ runs off-loop.

The legacy per-user index is still maintained during the P1 rollout so a
rollback to the previous image sees the same library.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from uuid import UUID, uuid4

from fastapi import HTTPException
from redis import Redis
from redis.exceptions import RedisError, WatchError
from rq.job import Job
from starlette.concurrency import run_in_threadpool

from app.core.config import AppConfig, get_config
from app.core.observability import current_request_id
from app.services.job_queue import DocumentQueue, LIVE_STATES
from app.services.quotas import document_quota_error
from app.services.failures import ERROR_MESSAGES, stage_failure

PREFIX = "doctrace:library:v2"
PUBLIC_FIELDS = (
    "doc_id", "name", "size_bytes", "status", "chunks_count", "warnings", "error", "created_at", "updated_at",
)
ADMIN_FIELDS = (
    "doc_id", "workspace_id", "owner_user_id", "status", "chunks_count", "size_bytes",
    "created_at", "updated_at", "error_code",
    "job_id", "request_id", "attempt_number", "queue_state",
)


def public_document(document: dict) -> dict:
    return {key: document.get(key) for key in PUBLIC_FIELDS}


def admin_document(document: dict) -> dict:
    """Never use the owner serializer in administrative endpoints."""
    result = {key: document.get(key) for key in ADMIN_FIELDS}
    result["error_code"] = document.get("error_code") if document.get("error_code") in ERROR_MESSAGES else None
    return result


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def document_key(doc_id: str) -> str:
    return f"{PREFIX}:document:{doc_id}"


def workspace_user_key(workspace_id: str, user_id: str) -> str:
    return f"{PREFIX}:workspace:{workspace_id}:user:{user_id}:documents"


def workspace_key(workspace_id: str) -> str:
    return f"{PREFIX}:workspace:{workspace_id}:documents"


def global_key() -> str:
    return f"{PREFIX}:documents"


def legacy_user_key(user_id: str) -> str:
    """Previous image's index; keep it accurate until the rollout is complete."""
    return f"{PREFIX}:user:{user_id}:documents"


def normalize_document(document: dict | None) -> dict | None:
    """Treat a pre-workspace record as belonging to the owner's personal workspace."""
    if document is None:
        return None
    if not document.get("owner_user_id"):
        document["owner_user_id"] = document.get("user_id")
    if not document.get("workspace_id"):
        document["workspace_id"] = document.get("owner_user_id")
    return document


def read_document(connection, doc_id: str) -> dict | None:
    raw = connection.hget(document_key(doc_id), "data")
    return normalize_document(json.loads(raw)) if raw else None


def write_document(pipeline, document: dict) -> None:
    pipeline.hset(document_key(document["doc_id"]), "data", json.dumps(document))


def owned(document: dict | None, workspace_id: str, user_id: str) -> dict:
    if (not document or document.get("status") == "deleted"
            or document.get("owner_user_id") != user_id
            or document.get("workspace_id") != workspace_id):
        raise HTTPException(404, "Không tìm thấy tài liệu.")
    return document


class DocumentRepository:
    def __init__(self, config: AppConfig):
        self.config = config

    def _run_sync(self, action, *args):
        # Also used by workspace admission while its short Postgres transaction
        # holds membership locks. That entire operation runs in one worker thread.
        try:
            with Redis.from_url(self.config.redis_url, socket_connect_timeout=5, socket_timeout=10) as connection:
                return action(connection, *args)
        except RedisError as exc:
            raise HTTPException(503, "Không thể kết nối thư viện hoặc xếp hàng. Vui lòng thử lại.") from exc

    async def _run(self, action, *args):
        return await run_in_threadpool(self._run_sync, action, *args)

    async def check_available(self) -> None:
        await self._run(lambda connection: connection.ping())

    def _get(self, connection, workspace_id: str, user_id: str, doc_id: str) -> dict:
        try:
            UUID(doc_id)
        except ValueError:
            raise HTTPException(404, "Không tìm thấy tài liệu.") from None
        queue = DocumentQueue(self.config, connection)
        for _ in range(10):
            with connection.pipeline() as pipe:
                try:
                    pipe.watch(document_key(doc_id))
                    document = owned(read_document(pipe, doc_id), workspace_id, user_id)
                    # Business outcomes outlive RQ result keys. A finished job can
                    # also mean an invalid PDF; only the task can publish ready.
                    if document["status"] not in ("queued", "processing", "deleting"):
                        return document
                    pipe.watch(Job.key_for(document["job_id"]))
                    state = queue.status(document["job_id"])
                    if state in LIVE_STATES:
                        status = ("deleting" if document["job_kind"] == "delete" else
                                  "processing" if state == "started" else "queued")
                        error = None
                    else:
                        status = "delete_error" if document["job_kind"] == "delete" else "error"
                        error = "Công việc bị gián đoạn hoặc không còn trong hàng đợi. Vui lòng thử lại."
                    if (status, error) == (document["status"], document["error"]):
                        return document
                    document.update(status=status, error=error, error_code="job_interrupted" if error else None,
                                    updated_at=now())
                    pipe.multi()
                    write_document(pipe, document)
                    if error:
                        stage_failure(pipe, document, "job_interrupted")
                    pipe.execute()
                    return document
                except WatchError:
                    continue
        raise HTTPException(409, "Tài liệu đang thay đổi. Vui lòng thử lại.")

    def get_sync(self, workspace_id: str, user_id: str, doc_id: str) -> dict:
        return self._run_sync(self._get, workspace_id, user_id, doc_id)

    async def get(self, workspace_id: str, user_id: str, doc_id: str) -> dict:
        return await run_in_threadpool(self.get_sync, workspace_id, user_id, doc_id)

    async def transcript_documents(self, workspace_id: str, user_id: str, doc_ids: list[str]) -> dict:
        """Batch-read visibility from the authoritative catalog, failing closed.

        A committed Redis delete hides content even if the following Postgres
        update failed. Missing records also hide transcripts. Reindexing only
        makes sources stale and does not hide conversation content.
        """
        def read(connection):
            with connection.pipeline(transaction=False) as pipe:
                for doc_id in doc_ids:
                    pipe.hget(document_key(doc_id), "data")
                records = pipe.execute()
            visible = {}
            for doc_id, raw in zip(doc_ids, records):
                document = normalize_document(json.loads(raw)) if raw else None
                try:
                    document = owned(document, workspace_id, user_id)
                except HTTPException as exc:
                    if exc.status_code != 404:
                        raise
                    continue
                if (document["status"] not in ("deleting", "delete_error")
                        and not document.get("delete_requested_at")):
                    visible[doc_id] = document
            return visible
        return await self._run(read) if doc_ids else {}

    async def list(self, workspace_id: str, user_id: str, limit: int, offset: int) -> dict:
        def listing(connection):
            ids = connection.zrevrange(workspace_user_key(workspace_id, user_id), offset, offset + limit)
            items = []
            for identifier in ids:
                try:
                    items.append(public_document(
                        self._get(connection, workspace_id, user_id, identifier.decode())
                    ))
                except HTTPException as exc:
                    if exc.status_code != 404:
                        raise
            return {"items": items[:limit], "has_more": len(items) > limit}
        return await self._run(listing)

    def create_sync(self, document: dict, *, limit: int) -> dict:
        """Called only after PDF retention; create the catalog and first job atomically.

        ``limit`` is the workspace document cap. The workspace index is watched
        and re-counted inside the same optimistic transaction so two uploads
        cannot both take the last slot.
        """
        if limit < 0:
            raise ValueError("Document limit cannot be negative")
        workspace_id = str(document.get("workspace_id") or "")
        owner_user_id = str(document.get("owner_user_id") or document.get("user_id") or "")
        if not workspace_id or not owner_user_id:
            raise ValueError("A document requires workspace_id and owner_user_id")

        def create(connection):
            timestamp = now()
            record = {**document, "user_id": owner_user_id, "owner_user_id": owner_user_id,
                      "workspace_id": workspace_id,
                      "request_id": current_request_id(),
                      "status": "queued", "chunks_count": 0, "warnings": [], "error": None, "error_code": None,
                      "created_at": timestamp, "updated_at": timestamp, "active_index_id": None,
                      "job_id": f"index-{document['doc_id']}", "job_kind": "index",
                      "attempt_number": 0, "attempt_id": None, "generations": []}
            score = datetime.fromisoformat(timestamp).timestamp()
            indexes = (
                workspace_user_key(workspace_id, owner_user_id),
                workspace_key(workspace_id),
                global_key(),
                legacy_user_key(owner_user_id),
            )
            for _ in range(10):
                with connection.pipeline() as pipe:
                    try:
                        pipe.watch(document_key(record["doc_id"]))
                        existing = read_document(pipe, record["doc_id"])
                        if existing:
                            return owned(existing, workspace_id, owner_user_id)
                        pipe.watch(workspace_key(workspace_id))
                        used = int(pipe.zcard(workspace_key(workspace_id)))
                        if used >= limit:
                            raise document_quota_error(limit, used)
                        pipe.multi()
                        write_document(pipe, record)
                        for index in indexes:
                            pipe.zadd(index, {record["doc_id"]: score})
                        DocumentQueue(self.config, connection).enqueue(
                            record["doc_id"], record["job_id"], "index", pipe)
                        pipe.execute()
                        return record
                    except WatchError:
                        continue
            raise HTTPException(409, "Tài liệu đang thay đổi. Vui lòng thử lại.")
        return self._run_sync(create)

    async def create(self, document: dict, *, limit: int) -> dict:
        """Internal catalog primitive; HTTP uploads use WorkspaceService admission."""
        return await run_in_threadpool(self.create_sync, document, limit=limit)

    def queue_sync(self, workspace_id: str, user_id: str, doc_id: str, kind: str) -> dict:
        if kind not in ("index", "delete"):
            raise ValueError("Unknown document task")

        def enqueue(connection):
            self._get(connection, workspace_id, user_id, doc_id)  # Reconcile pre-task failures/expired RQ keys first.
            queue = DocumentQueue(self.config, connection)
            job_id = f"{kind}-{uuid4()}"
            for _ in range(10):
                with connection.pipeline() as pipe:
                    try:
                        pipe.watch(document_key(doc_id))
                        document = owned(read_document(pipe, doc_id), workspace_id, user_id)
                        if document["job_id"] == job_id:
                            return document  # A retried EXEC read its own committed enqueue.
                        pipe.watch(Job.key_for(document["job_id"]))
                        if queue.status(document["job_id"]) in LIVE_STATES:
                            raise HTTPException(409, "Hãy chờ công việc hiện tại kết thúc trước khi xóa hoặc thử lại.")
                        allowed = ("error",) if kind == "index" else ("ready", "error", "delete_error")
                        if document["status"] not in allowed:
                            raise HTTPException(409, "Tài liệu chưa thể thực hiện thao tác này.")
                        document.update(job_id=job_id, job_kind=kind, attempt_number=0, attempt_id=None,
                                        request_id=current_request_id(),
                                        status="queued" if kind == "index" else "deleting", error=None, error_code=None,
                                        active_index_id=None, updated_at=now())
                        if kind == "delete":
                            document.setdefault("delete_requested_at", document["updated_at"])
                        pipe.multi()
                        write_document(pipe, document)
                        queue.enqueue(doc_id, job_id, kind, pipe)
                        pipe.execute()
                        return document
                    except WatchError:
                        continue
                    except RedisError:
                        # EXEC may have committed before the connection broke.
                        current = read_document(connection, doc_id)
                        if current and current["job_id"] == job_id:
                            return current
                        raise
            raise HTTPException(409, "Tài liệu đang thay đổi. Vui lòng thử lại.")
        return self._run_sync(enqueue)

    async def queue(self, workspace_id: str, user_id: str, doc_id: str, kind: str) -> dict:
        """Catalog primitive; HTTP deletion uses TranscriptService's lifecycle fence."""
        return await run_in_threadpool(self.queue_sync, workspace_id, user_id, doc_id, kind)

    def count_workspace_sync(self, workspace_id: str, user_id: str | None = None) -> int:
        """Number of catalogued (not necessarily ready) documents in a workspace."""
        def count(connection):
            key = workspace_user_key(workspace_id, user_id) if user_id else workspace_key(workspace_id)
            return int(connection.zcard(key))
        return self._run_sync(count)

    async def count_workspace(self, workspace_id: str, user_id: str | None = None) -> int:
        return await run_in_threadpool(self.count_workspace_sync, workspace_id, user_id)

    async def internal_document(self, doc_id: str) -> dict | None:
        return await self._run(read_document, doc_id)

    def purge_snapshot_sync(self, workspace_id: str) -> list[dict]:
        """Called with the exclusive workspace admission lock held in Postgres.

        Deleted hashes outlive all library indexes. Scan canonical hashes too so
        a hard purge includes old tombstones and pre-workspace records. SCAN is
        incremental; this administrative operation never uses blocking KEYS.
        """
        def snapshot(connection):
            queue = DocumentQueue(self.config, connection)
            documents = {}
            def include(doc, doc_id):
                if doc["doc_id"] != doc_id:
                    raise HTTPException(409, "Workspace catalog is inconsistent.")
                if queue.status(doc.get("job_id")) in LIVE_STATES:
                    raise HTTPException(409, detail={"code": "workspace_jobs_live", "message": "Hãy chờ các job kết thúc trước khi xóa workspace."})
                documents[doc_id] = {"doc_id": doc_id, "owner_user_id": doc["owner_user_id"]}

            for raw_id, _ in connection.zscan_iter(workspace_key(workspace_id), count=100):
                doc = read_document(connection, raw_id.decode())
                # Missing/foreign catalog records must not silently orphan PDFs.
                if not doc or doc["workspace_id"] != workspace_id:
                    raise HTTPException(409, "Workspace catalog is inconsistent.")
                include(doc, raw_id.decode())
            for key in connection.scan_iter(match=f"{PREFIX}:document:*", count=100):
                doc_id = key.decode().rsplit(":", 1)[1]
                if doc_id in documents:
                    continue
                doc = read_document(connection, doc_id)
                if doc and doc["workspace_id"] == workspace_id:
                    include(doc, doc_id)
            return list(documents.values())
        return self._run_sync(snapshot)

    def purge_cleanup_sync(self, workspace_id: str, documents: list[dict]) -> None:
        """Only after a durable manifest says every external deletion finished.

        Missing hashes are an idempotent replay of a previously accepted cleanup.
        The SQL workspace lock fences every enqueue while this runs.
        """
        def cleanup(connection):
            if connection.zcard(workspace_key(workspace_id)):
                raise HTTPException(409, "Workspace still has documents.")
            for item in documents:
                key = document_key(item["doc_id"])
                with connection.pipeline() as pipe:
                    pipe.watch(key)
                    doc = read_document(pipe, item["doc_id"])
                    if doc and (doc["workspace_id"] != workspace_id or doc["owner_user_id"] != item["owner_user_id"]
                                or doc["status"] != "deleted"):
                        raise HTTPException(409, "Document cleanup is incomplete.")
                    pipe.multi()
                    pipe.delete(key)
                    for index in (workspace_user_key(workspace_id, item["owner_user_id"]),
                                  legacy_user_key(item["owner_user_id"]), global_key()):
                        pipe.zrem(index, item["doc_id"])
                    pipe.execute()
        self._run_sync(cleanup)

    def admin_catalog_sync(self, workspace_id: str | None = None, *, status: str | None = None,
                           limit: int = 100, offset: int = 0) -> dict:
        """Bounded metadata scan, authorized by the admin service before entry.

        Offset is a catalog scan cursor, not a filtered-row offset. Even with a
        selective status filter, one request reads at most limit records.
        """
        def listing(connection):
            key = workspace_key(workspace_id) if workspace_id else global_key()
            identifiers = connection.zrevrange(key, offset, offset + limit)
            items = []
            for raw_id in identifiers[:limit]:
                doc_id = raw_id.decode()
                doc = read_document(connection, doc_id)
                if not doc or (workspace_id and doc["workspace_id"] != workspace_id):
                    continue
                try:
                    doc = self._get(connection, doc["workspace_id"], doc["owner_user_id"], doc_id)
                except HTTPException as exc:
                    if exc.status_code == 404:
                        continue
                    raise
                if status is None or doc["status"] == status:
                    doc["queue_state"] = DocumentQueue(self.config, connection).status(doc.get("job_id"))
                    items.append(admin_document(doc))
            return {"items": items, "next_offset": offset + limit if len(identifiers) > limit else None}
        return self._run_sync(listing)

    async def admin_catalog(self, workspace_id: str | None = None, *, status: str | None = None,
                            limit: int = 100, offset: int = 0) -> dict:
        return await run_in_threadpool(self.admin_catalog_sync, workspace_id, status=status, limit=limit, offset=offset)

    async def begin(self, doc_id: str, job_id: str, attempt_number: int) -> dict | None:
        def begin(connection):
            token = str(uuid4())
            for _ in range(10):
                with connection.pipeline() as pipe:
                    try:
                        pipe.watch(document_key(doc_id))
                        document = read_document(pipe, doc_id)
                        if document and document["job_id"] == job_id and document["attempt_id"] == token:
                            return {"job_id": job_id, "attempt_id": token, "kind": document["job_kind"],
                                    "document": document}
                        if (not document or document["job_id"] != job_id
                                or document["status"] in ("ready", "deleted")
                                or attempt_number <= document["attempt_number"]):
                            return None
                        document.update(attempt_number=attempt_number, attempt_id=token, error=None, error_code=None,
                                        status="processing" if document["job_kind"] == "index" else "deleting",
                                        updated_at=now())
                        if document["job_kind"] == "index":
                            document["generations"].append(token)
                        pipe.multi()
                        write_document(pipe, document)
                        pipe.execute()
                        return {"job_id": job_id, "attempt_id": token, "kind": document["job_kind"],
                                "document": document}
                    except WatchError:
                        continue
            raise HTTPException(409, "Tài liệu đang thay đổi. Vui lòng thử lại.")
        return await self._run(begin)

    async def finish(self, attempt: dict, *, error=None, error_code=None, retryable=False, chunks_count=0, warnings=None) -> bool:
        def finish(connection):
            doc_id = attempt["document"]["doc_id"]
            for _ in range(10):
                with connection.pipeline() as pipe:
                    try:
                        pipe.watch(document_key(doc_id))
                        document = read_document(pipe, doc_id)
                        if (not document or document["job_id"] != attempt["job_id"]
                                or document["attempt_id"] != attempt["attempt_id"]):
                            return False
                        if document["status"] in ("ready", "deleted"):
                            return error is None  # An uncertain success must never turn into failure.
                        deleting = attempt["kind"] == "delete"
                        if error:
                            status = ("deleting" if deleting else "queued") if retryable else (
                                "delete_error" if deleting else "error")
                            code = error_code or ("delete_failed" if deleting else "index_failed")
                            document.update(status=status, error=None if retryable else error,
                                            error_code=None if retryable else code)
                        else:
                            document.update(status="deleted" if deleting else "ready", error=None, error_code=None,
                                            active_index_id=None if deleting else attempt["attempt_id"],
                                            chunks_count=chunks_count, warnings=warnings or [])
                        document["updated_at"] = now()
                        pipe.multi()
                        write_document(pipe, document)
                        if error and not retryable:
                            stage_failure(pipe, document, code)
                        if document["status"] == "deleted":
                            owner_user_id = document["owner_user_id"]
                            workspace_id = document["workspace_id"]
                            for index in (
                                workspace_user_key(workspace_id, owner_user_id),
                                workspace_key(workspace_id),
                                global_key(),
                                legacy_user_key(owner_user_id),
                            ):
                                pipe.zrem(index, doc_id)
                        pipe.execute()
                        return error is None
                    except WatchError:
                        continue
            raise HTTPException(409, "Tài liệu đang thay đổi. Vui lòng thử lại.")
        return await self._run(finish)


def get_document_repository() -> DocumentRepository:
    return DocumentRepository(get_config())
