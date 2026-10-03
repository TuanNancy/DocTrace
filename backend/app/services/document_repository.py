"""Owner-scoped Redis library. Catalog records have no TTL; RQ jobs do.

All writes use WATCH to serialize changes to one document. Enqueue and metadata
share MULTI/EXEC on the same Redis instance. Synchronous Redis/RQ runs off-loop.
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
from app.services.job_queue import DocumentQueue, LIVE_STATES

PREFIX = "doctrace:library:v2"
PUBLIC_FIELDS = (
    "doc_id", "name", "size_bytes", "status", "chunks_count", "warnings", "error", "created_at", "updated_at",
)


def public_document(document: dict) -> dict:
    return {key: document.get(key) for key in PUBLIC_FIELDS}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def document_key(doc_id: str) -> str:
    return f"{PREFIX}:document:{doc_id}"


def catalog_key(user_id: str) -> str:
    return f"{PREFIX}:user:{user_id}:documents"


def read_document(connection, doc_id: str) -> dict | None:
    raw = connection.hget(document_key(doc_id), "data")
    return json.loads(raw) if raw else None


def write_document(pipeline, document: dict) -> None:
    pipeline.hset(document_key(document["doc_id"]), "data", json.dumps(document))


def owned(document: dict | None, user_id: str) -> dict:
    if not document or document["user_id"] != user_id or document["status"] == "deleted":
        raise HTTPException(404, "Không tìm thấy tài liệu.")
    return document


class DocumentRepository:
    def __init__(self, config: AppConfig):
        self.config = config

    async def _run(self, action, *args):
        def call():
            # Short-lived clients avoid leaking pools from request dependencies and
            # never share pre-fork connections with the RQ work horse.
            with Redis.from_url(self.config.redis_url, socket_connect_timeout=5, socket_timeout=10) as connection:
                return action(connection, *args)
        try:
            return await run_in_threadpool(call)
        except RedisError as exc:
            raise HTTPException(503, "Không thể kết nối thư viện hoặc xếp hàng. Vui lòng thử lại.") from exc

    async def check_available(self) -> None:
        await self._run(lambda connection: connection.ping())

    def _get(self, connection, user_id: str, doc_id: str) -> dict:
        try:
            UUID(doc_id)
        except ValueError:
            raise HTTPException(404, "Không tìm thấy tài liệu.") from None
        queue = DocumentQueue(self.config, connection)
        for _ in range(10):
            with connection.pipeline() as pipe:
                try:
                    pipe.watch(document_key(doc_id))
                    document = owned(read_document(pipe, doc_id), user_id)
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
                    document.update(status=status, error=error, updated_at=now())
                    pipe.multi()
                    write_document(pipe, document)
                    pipe.execute()
                    return document
                except WatchError:
                    continue
        raise HTTPException(409, "Tài liệu đang thay đổi. Vui lòng thử lại.")

    async def get(self, user_id: str, doc_id: str) -> dict:
        return await self._run(self._get, user_id, doc_id)

    async def list(self, user_id: str, limit: int, offset: int) -> dict:
        def listing(connection):
            ids = connection.zrevrange(catalog_key(user_id), offset, offset + limit)
            items = []
            for identifier in ids:
                try:
                    items.append(public_document(self._get(connection, user_id, identifier.decode())))
                except HTTPException as exc:
                    if exc.status_code != 404:
                        raise
            return {"items": items[:limit], "has_more": len(items) > limit}
        return await self._run(listing)

    async def create(self, document: dict) -> dict:
        """Called only after PDF retention; create the catalog and first job atomically."""
        def create(connection):
            timestamp = now()
            record = {**document, "status": "queued", "chunks_count": 0, "warnings": [], "error": None,
                      "created_at": timestamp, "updated_at": timestamp, "active_index_id": None,
                      "job_id": f"index-{document['doc_id']}", "job_kind": "index",
                      "attempt_number": 0, "attempt_id": None, "generations": []}
            for _ in range(10):
                with connection.pipeline() as pipe:
                    try:
                        pipe.watch(document_key(record["doc_id"]))
                        existing = read_document(pipe, record["doc_id"])
                        if existing:
                            return owned(existing, record["user_id"])
                        pipe.multi()
                        write_document(pipe, record)
                        pipe.zadd(catalog_key(record["user_id"]), {
                            record["doc_id"]: datetime.fromisoformat(timestamp).timestamp(),
                        })
                        DocumentQueue(self.config, connection).enqueue(
                            record["doc_id"], record["job_id"], "index", pipe)
                        pipe.execute()
                        return record
                    except WatchError:
                        continue
            raise HTTPException(409, "Tài liệu đang thay đổi. Vui lòng thử lại.")
        return await self._run(create)

    async def queue(self, user_id: str, doc_id: str, kind: str) -> dict:
        if kind not in ("index", "delete"):
            raise ValueError("Unknown document task")

        def enqueue(connection):
            self._get(connection, user_id, doc_id)  # Reconcile pre-task failures/expired RQ keys first.
            queue = DocumentQueue(self.config, connection)
            job_id = f"{kind}-{uuid4()}"
            for _ in range(10):
                with connection.pipeline() as pipe:
                    try:
                        pipe.watch(document_key(doc_id))
                        document = owned(read_document(pipe, doc_id), user_id)
                        if document["job_id"] == job_id:
                            return document  # A retried EXEC read its own committed enqueue.
                        pipe.watch(Job.key_for(document["job_id"]))
                        if queue.status(document["job_id"]) in LIVE_STATES:
                            raise HTTPException(409, "Hãy chờ công việc hiện tại kết thúc trước khi xóa hoặc thử lại.")
                        allowed = ("error",) if kind == "index" else ("ready", "error", "delete_error")
                        if document["status"] not in allowed:
                            raise HTTPException(409, "Tài liệu chưa thể thực hiện thao tác này.")
                        document.update(job_id=job_id, job_kind=kind, attempt_number=0, attempt_id=None,
                                        status="queued" if kind == "index" else "deleting", error=None,
                                        active_index_id=None, updated_at=now())
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
        return await self._run(enqueue)

    async def internal_document(self, doc_id: str) -> dict | None:
        return await self._run(read_document, doc_id)

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
                        document.update(attempt_number=attempt_number, attempt_id=token, error=None,
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

    async def finish(self, attempt: dict, *, error=None, retryable=False, chunks_count=0, warnings=None) -> bool:
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
                            document.update(status=status, error=None if retryable else error)
                        else:
                            document.update(status="deleted" if deleting else "ready", error=None,
                                            active_index_id=None if deleting else attempt["attempt_id"],
                                            chunks_count=chunks_count, warnings=warnings or [])
                        document["updated_at"] = now()
                        pipe.multi()
                        write_document(pipe, document)
                        if document["status"] == "deleted":
                            pipe.zrem(catalog_key(document["user_id"]), doc_id)
                        pipe.execute()
                        return error is None
                    except WatchError:
                        continue
            raise HTTPException(409, "Tài liệu đang thay đổi. Vui lòng thử lại.")
        return await self._run(finish)


def get_document_repository() -> DocumentRepository:
    return DocumentRepository(get_config())
